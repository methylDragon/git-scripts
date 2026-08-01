"""Command logic for git-gh-align-pr-bases-and-sync-stacks."""

import os
from dataclasses import dataclass

import pygit2
import questionary
from rich.panel import Panel

from git_scripts.gh.api import (
    GhExecutionError,
    GitHubPr,
    check_gh_installed,
    check_gh_stack_installed,
    get_open_prs,
    gh_pr_create,
    gh_pr_edit,
    gh_stack_checkout,
    gh_stack_link,
    gh_stack_unstack,
)
from git_scripts.git.reads import get_repo
from git_scripts.git.topology import (
    check_remote_push_parity,
    check_remote_trunk_ancestry,
    check_stack_continuity,
    find_linear_stack,
    get_parent_branch,
    sort_branches_bottom_to_top,
)
from git_scripts.ui import UI


@dataclass
class PrEditAction:
    """Action for editing an existing PR's base branch."""

    branch: str
    old_base: str
    new_base: str
    reason: str
    url: str
    pr_number: str | None = None


@dataclass
class PrCreateAction:
    """Action for creating a missing PR."""

    branch: str
    base: str
    title: str
    description: str
    url: str | None = None


def _get_pr_template(repo_path: str) -> str:
    """Attempts to find and read a GitHub PR template from the repository."""
    candidate_paths = [
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/pull_request_template.md",
        "PULL_REQUEST_TEMPLATE.md",
        "pull_request_template.md",
    ]
    for rel_path in candidate_paths:
        full_path = os.path.join(repo_path, rel_path)
        if os.path.isfile(full_path):
            try:
                with open(full_path, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
    return ""


def _humanize_branch_name(branch: str) -> str:
    """Converts branch name like 'feat/add-login' to 'Add login'."""
    # Strip prefix up to the last slash
    if "/" in branch:
        branch = branch.rsplit("/", 1)[-1]

    # Replace hyphens and underscores with spaces
    branch = branch.replace("-", " ").replace("_", " ")

    # Capitalize first letter
    if branch:
        branch = branch[0].upper() + branch[1:]

    return branch


def _compute_pr_metadata(
    repo: pygit2.Repository, branch: str, base: str, template: str
) -> tuple[str, str]:
    """Computes the PR title and description based on commits ahead of base.

    1 commit: title=commit summary, desc=commit body.
    >1 commit: title=humanized branch name, desc=template (or blank).
    """
    try:
        branch_commit = repo.revparse_single(branch)
        base_commit = repo.revparse_single(base)
    except (KeyError, ValueError, TypeError):
        # Fallback if something is detached or missing
        return _humanize_branch_name(branch), template

    walker = repo.walk(branch_commit.id, pygit2.enums.SortMode.TOPOLOGICAL)
    walker.hide(base_commit.id)

    commits = list(walker)

    if len(commits) == 1:
        commit = commits[0]
        msg = commit.message.strip()
        lines = msg.split("\n", 1)
        title = lines[0].strip()
        description = lines[1].strip() if len(lines) > 1 else ""
        if template:
            if description:
                description = f"{description}\n\n{template}"
            else:
                description = template
        return title, description
    else:
        return _humanize_branch_name(branch), template


def calculate_pr_actions(
    repo: pygit2.Repository,
    branches: set[str],
    pr_state: dict[str, GitHubPr],
    target_trunk: str = "main",
    create_missing: bool = False,
) -> tuple[list[PrEditAction], list[PrCreateAction]]:
    """Map local topology to required PR edits and creations."""
    parent_map = {}
    for branch in branches:
        parent_map[branch] = get_parent_branch(repo, branch, branches)

    edits = []
    creates = []

    # Cache the template read once per run
    pr_template = _get_pr_template(repo.path)

    for branch in branches:
        if branch not in pr_state:
            parent = parent_map.get(branch)
            base = parent if parent else target_trunk
            title, description = _compute_pr_metadata(
                repo, branch, base, pr_template
            )
            creates.append(
                PrCreateAction(
                    branch=branch,
                    base=base,
                    title=title,
                    description=description,
                )
            )
            continue

        current_base = pr_state[branch].base_ref
        pr_url = pr_state[branch].url
        pr_number = str(pr_state[branch].number)

        curr_ancestor = parent_map.get(branch)
        skipped = False

        if not create_missing:
            while curr_ancestor is not None and curr_ancestor not in pr_state:
                curr_ancestor = parent_map.get(curr_ancestor)
                skipped = True

        expected_base = curr_ancestor if curr_ancestor else target_trunk

        if current_base != expected_base:
            reason = "Matches local topology"
            if skipped and not create_missing:
                reason = "Matches nearest ancestor with an open PR"

            edits.append(
                PrEditAction(
                    branch=branch,
                    old_base=current_base,
                    new_base=expected_base,
                    reason=reason,
                    url=pr_url,
                    pr_number=pr_number,
                )
            )

    return edits, creates


def _group_into_stacks(
    repo: pygit2.Repository, branches: set[str]
) -> dict[str, list[str]]:
    """Groups branches into distinct topological stacks."""
    parent_map = {b: get_parent_branch(repo, b, branches) for b in branches}
    parents = set(parent_map.values()) - {None}
    tips = [b for b in branches if b not in parents]

    stacks = {}
    for tip in sorted(tips):
        curr: str | None = tip
        stack = []
        while curr and curr in branches:
            stack.append(curr)
            curr = parent_map.get(curr)
        stacks[tip] = stack[::-1]  # from bottom to top
    return stacks


def _handle_interactive_selection(
    repo: pygit2.Repository, branches: set[str], ui: UI
) -> set[str]:
    stacks = _group_into_stacks(repo, branches)
    choices = []
    for tip, stack in stacks.items():
        label = " ➔ ".join(stack)
        choices.append(questionary.Choice(title=label, value=tip))

    selected_tips = ui.ask_checkbox(
        "Select stacks to align (Space to toggle, Enter to confirm):",
        choices=choices,
    )
    if not selected_tips:
        return set()

    final_branches = set()
    for tip in selected_tips:
        final_branches.update(stacks[tip])
    return final_branches


def _get_selected_branches(
    repo: pygit2.Repository,
    prefix: str | None,
    current_stack_only: bool,
    all_matching: bool,
    ui: UI,
    target: str,
    interactive: bool = False,
) -> set[str] | None:
    all_local_branches = {
        ref[11:] for ref in repo.references if ref.startswith("refs/heads/")
    }

    try:
        head = repo.head.shorthand
    except pygit2.GitError:
        head = None

    if prefix:
        matched = {b for b in all_local_branches if b.startswith(prefix)}
        if not matched:
            ui.print(f"❌  No branches found matching prefix '{prefix}'")
            return None

        if (
            head in matched
            and not current_stack_only
            and not all_matching
            and not interactive
            and not ui.auto_yes
        ):
            action = ui.ask_choice(
                f"You are on '{head}'. Which branches do you want to align?",
                choices=[
                    "Current stack only",
                    "All matching prefix branches",
                    "Select which stacks to align",
                    "Cancel",
                ],
                default="Current stack only",
            )
            if action == "Cancel":
                return set()
            elif action == "Current stack only":
                current_stack_only = True
            elif action == "Select which stacks to align":
                interactive = True
            else:
                all_matching = True

        if interactive:
            return _handle_interactive_selection(repo, matched, ui)

        if current_stack_only:
            if head is None or head not in matched:
                ui.print(
                    f"❌  Cannot use --current: HEAD ({head}) "
                    f"does not match prefix '{prefix}'"
                )
                return None
            return find_linear_stack(repo, head, matched)
        else:
            return matched
    else:
        if interactive:
            return _handle_interactive_selection(repo, all_local_branches, ui)

        if head == target or not head:
            ui.print(f"❌  Cannot align: HEAD is on {head or 'detached'}.")
            return None
        return find_linear_stack(
            repo, head, all_local_branches, stop_at=target
        )


def _print_branch_summary(
    selected_branches: set[str], pr_state: dict[str, GitHubPr], ui: UI
) -> None:
    branches_with_prs = [b for b in selected_branches if b in pr_state]
    branches_without_prs = [b for b in selected_branches if b not in pr_state]

    summary_text = ""
    if branches_with_prs:
        summary_text += "[green]Branches with open PRs:[/green]\n"
        for b in sorted(branches_with_prs):
            base = pr_state[b].base_ref
            url = pr_state[b].url
            summary_text += (
                f"  - [yellow]{b}[/yellow] ([dim]base:[/dim] "
                f"[cyan]{base}[/cyan])\n    [dim]🔗  {url}[/dim]\n"
            )

    if branches_without_prs:
        if summary_text:
            summary_text += "\n"
        summary_text += "[yellow]Branches missing PRs:[/yellow]\n"
        for b in sorted(branches_without_prs):
            summary_text += f"  - [yellow]{b}[/yellow]\n"

    b_plural = "branch" if len(selected_branches) == 1 else "branches"
    title_str = (
        f"[bold cyan]Branch Summary "
        f"({len(selected_branches)} {b_plural})[/bold cyan]"
    )
    ui.print(
        Panel(
            summary_text.rstrip(),
            title=title_str,
            border_style="cyan",
            expand=False,
        )
    )


def _prompt_creates(
    creates: list[PrCreateAction], create_missing: bool, ui: UI
) -> list[PrCreateAction]:
    if not creates:
        return []

    ui.print("\n[bold green]Potential PR Creations (Drafts):[/bold green]")
    if not ui.auto_yes:
        choices = []
        for c in creates:
            title = [
                ("ansiyellow", c.branch),
                ("", " (base: "),
                ("ansigreen", c.base),
                ("", ") - "),
                ("ansicyan", f'"{c.title}"'),
            ]
            choices.append(questionary.Choice(title=title, value=c.branch))

        selected = ui.ask_checkbox(
            "Select which missing PRs you want to create "
            "(Space to toggle, Enter to confirm):",
            choices=choices,
        )
        if not selected:
            return []

        filtered = [c for c in creates if c.branch in selected]
        ui.print("\n[bold green]Will create PRs for:[/bold green]")
        for action in filtered:
            ui.print(
                f"  - [yellow]{action.branch}[/yellow] "
                f"([dim]base:[/dim] [green]{action.base}[/green]) - "
                f'[cyan]"{action.title}"[/cyan]'
            )
        return filtered
    else:
        if create_missing:
            for action in creates:
                ui.print(
                    f"  - [yellow]{action.branch}[/yellow] "
                    f"([dim]base:[/dim] [green]{action.base}[/green]) - "
                    f'[cyan]"{action.title}"[/cyan]'
                )
            return creates
        return []


def _execute_edits(edits: list[PrEditAction], repo_path: str, ui: UI) -> bool:
    success = True
    if edits:
        ui.print("\n🚀  Updating PR bases via GitHub API...")
        for action in edits:
            try:
                gh_pr_edit(
                    repo_path,
                    action.branch,
                    action.new_base,
                    action.pr_number,
                )
                ui.print(
                    f"  ✅  Updated [yellow]{action.branch}[/yellow] ➔ "
                    f"[green]{action.new_base}[/green]"
                )
            except GhExecutionError as e:
                msg = (
                    f"  ❌  Failed to update [yellow]{action.branch}[/yellow]"
                )
                ui.print(f"{msg}: {e}")
                success = False
    return success


def _execute_creates(
    creates: list[PrCreateAction], repo_path: str, ui: UI
) -> bool:
    success = True
    if creates:
        ui.print("\n🚀  Creating missing PRs via GitHub API...")
        for action in creates:
            try:
                import time

                time.sleep(1)
                url = gh_pr_create(
                    repo_path,
                    action.branch,
                    action.base,
                    title=action.title,
                    body=action.description,
                )
                action.url = url
                ui.print(
                    f"  ✅  Created Draft PR for "
                    f"[yellow]{action.branch}[/yellow]"
                    f" ➔ [green]{action.base}[/green]\n"
                    f"      [dim]🔗  {url}[/dim]"
                )
            except GhExecutionError as e:
                err_msg = str(e)
                ui.print(
                    f"  ❌  Failed to create PR for "
                    f"[yellow]{action.branch}[/yellow]: "
                    f"[dim]{err_msg.strip()}[/dim]"
                )
                success = False
    return success


def _print_final_summary(
    edits: list[PrEditAction],
    creates: list[PrCreateAction],
    skipped_branches: set[str],
    pr_state: dict[str, GitHubPr],
    ui: UI,
    stack_branches: list[str] | None = None,
) -> None:
    final_summary = ""
    if edits:
        pr_plural = "PR" if len(edits) == 1 else "PRs"
        final_summary += (
            f"✅  Aligned base for [green]{len(edits)}[/green] {pr_plural}:\n"
        )
        for action in edits:
            final_summary += f"      - [yellow]{action.branch}[/yellow]\n"
            if action.url:
                final_summary += f"        [dim]🔗  {action.url}[/dim]\n"

    if creates:
        pr_plural = "PR" if len(creates) == 1 else "PRs"
        final_summary += (
            f"✅  Created [green]{len(creates)}[/green] new {pr_plural}:\n"
        )
        for create_action in creates:
            b = create_action.branch
            url = create_action.url
            final_summary += f"      - [yellow]{b}[/yellow]\n"
            if url:
                final_summary += f"        [dim]🔗  {url}[/dim]\n"

    if stack_branches:
        final_summary += (
            f"🔗  Synced GitHub stack for "
            f"[green]{len(stack_branches)}[/green] branches:\n"
        )
        for branch in stack_branches:
            final_summary += f"      - [yellow]{branch}[/yellow]\n"
            if branch in pr_state and pr_state[branch].url:
                url = pr_state[branch].url
                final_summary += f"        [dim]🔗  {url}[/dim]\n"

    if skipped_branches:
        b_plural = "branch" if len(skipped_branches) == 1 else "branches"
        final_summary += (
            f"⏭️   Skipped base alignment for "
            f"[yellow]{len(skipped_branches)}[/yellow] {b_plural}:\n"
        )
        for branch in sorted(skipped_branches):
            final_summary += f"      - [yellow]{branch}[/yellow]\n"
            if branch in pr_state and pr_state[branch].url:
                url = pr_state[branch].url
                final_summary += f"        [dim]🔗  {url}[/dim]\n"

    if not final_summary:
        return

    ui.print(
        Panel(
            final_summary.rstrip(),
            title="[bold cyan]Final Alignment Summary[/bold cyan]",
            border_style="cyan",
            expand=False,
        )
    )


def _verify_topology(
    repo: pygit2.Repository,
    selected_branches: set[str],
    target: str,
    ui: UI,
) -> tuple[bool, list[str] | None, dict[str, str | None]]:
    parent_map = {}
    for branch in selected_branches:
        parent_map[branch] = get_parent_branch(repo, branch, selected_branches)
    ordered = sort_branches_bottom_to_top(selected_branches, parent_map)

    if ordered:
        bottom_branch = ordered[0]
        if not check_remote_trunk_ancestry(repo, bottom_branch, target):
            ui.print(
                f"[red]❌ Validation Failed: Remote trunk divergence.[/red]\n"
                f"[yellow]Your local stack is not strictly ahead of "
                f"'{target}'. The remote base was likely updated.\n"
                f"Action required: Fetch the latest changes and rebase your "
                f"stack onto '{target}' before aligning PRs.[/yellow]"
            )
            return False, None, parent_map

        ok, broken_branch = check_stack_continuity(repo, ordered)
        if not ok:
            ui.print(
                f"[red]❌ Validation Failed: Stack continuity broken.[/red]\n"
                f"[yellow]Branch '{broken_branch}' is not a valid descendant "
                f"of its base branch.\n"
                f"Action required: Perform a cascading rebase to ensure a "
                f"strictly linear commit history across the stack.[/yellow]"
            )
            return False, None, parent_map

    ok, unpushed = check_remote_push_parity(repo, selected_branches)
    if not ok:
        ui.print(
            f"[red]❌ Validation Failed: Unpushed local changes.[/red]\n"
            f"[yellow]Branch '{unpushed}' has local commits that are not "
            f"pushed to the remote.\n"
            f"Action required: Push all branches in the stack before "
            f"aligning PR bases to prevent GitHub API rejections.[/yellow]"
        )
        return False, None, parent_map

    return True, ordered, parent_map


def _print_edits(edits: list[PrEditAction], ui: UI) -> None:
    if not edits:
        return
    ui.print("\n[bold cyan]Planned PR Base Edits:[/bold cyan]")
    for action in edits:
        ui.print(
            f"  - [yellow]{action.branch}[/yellow] "
            f"([red]{action.old_base}[/red] ➔ "
            f"[green]{action.new_base}[/green])\n"
            f"    [dim]🔗  {action.url}[/dim]\n"
            f"    [dim]💡  {action.reason}[/dim]"
        )


def _sync_gh_stack(
    repo_path: str,
    ordered: list[str],
    pr_state: dict[str, GitHubPr],
    parent_map: dict[str, str | None],
    target: str,
    ui: UI,
) -> bool:
    ui.print("\n[bold cyan]Stack Topology:[/bold cyan]")
    for idx, branch in enumerate(reversed(ordered)):
        stack_idx = len(ordered) - idx
        ui.print(f"({stack_idx}/{len(ordered)})  {branch}")

    if ordered:
        bottom_branch = ordered[0]
        base = parent_map.get(bottom_branch) or target
        ui.print(f"(base) {base}")

    if ui.auto_yes or ui.confirm(
        "\n🔗  Synchronize GitHub stack with local topology? "
        "(Unstacks and relinks via 'gh stack link')"
    ):
        pr_number = None
        for b in ordered:
            if b in pr_state and pr_state[b].url:
                url = pr_state[b].url
                parts = url.split("/")
                if parts and parts[-1].isdigit():
                    pr_number = parts[-1]
                    break

        if pr_number:
            ui.print(
                f"\n🔄  Checking out PR #{pr_number} to ensure "
                "local tracking..."
            )
            try:
                gh_stack_checkout(repo_path, pr_number)
            except GhExecutionError as e:
                ui.print(f"  ⚠️   Checkout failed: [dim]{str(e)}[/dim]")

        ui.print(
            "\n🗑️  Unstacking current remote stack state to ensure "
            "synchronization..."
        )
        try:
            gh_stack_unstack(repo_path)
            ui.print("  ✅  Unstacked successfully!")
        except GhExecutionError as e:
            ui.print(
                f"  ⚠️   Unstack failed (might not be stacked): "
                f"[dim]{str(e)}[/dim]"
            )

        ui.print("\n🚀  Linking stack on GitHub...")
        try:
            gh_stack_link(repo_path, ordered)
            ui.print("  ✅  Stack linked successfully!")
            return True
        except GhExecutionError as e:
            ui.print(
                f"  ❌  Failed to link stack: [dim]{str(e)}[/dim]\n"
                f"This usually happens if the base branch was updated "
                f"on the remote. Please fetch, rebase your stack, "
                f"push, and try again."
            )
            return False
    return False


def _check_auth(ui: UI) -> bool:
    if not check_gh_installed():
        ui.print(
            "[red]❌  Error: GitHub CLI ('gh') is not installed "
            "or not authenticated.[/red]"
        )
        ui.print(
            "Please install 'gh' and run 'gh auth login' to use this command."
        )
        return False
    return True


def execute_align_pr_bases_and_sync_stacks(
    repo_path: str,
    prefix: str | None = None,
    target: str = "main",
    current_stack_only: bool = False,
    all_matching: bool = False,
    create_missing: bool = False,
    interactive: bool = False,
    ui: UI | None = None,
) -> bool:
    """Aligns GitHub PR bases with local topology."""
    if ui is None:
        ui = UI()

    if not _check_auth(ui):
        return False

    repo = get_repo(repo_path)
    selected_branches = _get_selected_branches(
        repo, prefix, current_stack_only, all_matching, ui, target, interactive
    )

    if selected_branches is None:
        return False
    if not selected_branches:
        if prefix:
            ui.print("❌  Operation cancelled.")
        return True

    b_plural = "branch" if len(selected_branches) == 1 else "branches"
    ui.print(
        f"🔍  Analyzing topology for {len(selected_branches)} {b_plural}..."
    )

    ok, ordered_or_none, parent_map = _verify_topology(
        repo, selected_branches, target, ui
    )
    if not ok or ordered_or_none is None:
        return False

    ordered = ordered_or_none

    ui.print("🔄  Fetching GitHub PR states...")
    pr_state = get_open_prs(repo_path)

    _print_branch_summary(selected_branches, pr_state, ui)

    edits, creates = calculate_pr_actions(
        repo,
        selected_branches,
        pr_state,
        target_trunk=target,
        create_missing=create_missing,
    )

    _print_edits(edits, ui)
    creates = _prompt_creates(creates, create_missing, ui)

    action_branches = {a.branch for a in edits} | {c.branch for c in creates}
    skipped_branches = selected_branches - action_branches

    if not edits and not creates:
        ui.print(
            "\n✨  All GitHub PR bases are already aligned "
            "with local topology!"
        )
        success = True
    else:
        if not ui.auto_yes:
            if not ui.confirm("\n❓  Apply these changes to GitHub?"):
                ui.print("❌  Operation cancelled.")
                return True

        success_edits = _execute_edits(edits, repo_path, ui)
        success_creates = _execute_creates(creates, repo_path, ui)
        success = success_edits and success_creates

        if success:
            ui.print("\n🎉  All PR operations completed successfully!")
        else:
            ui.print("\n⚠️   Finished with some errors.")

    stack_linked = False
    if success and len(selected_branches) > 1:
        if check_gh_stack_installed():
            if _sync_gh_stack(
                repo_path, ordered, pr_state, parent_map, target, ui
            ):
                stack_linked = True
            else:
                success = False
        else:
            ui.print(
                "\n💡  [dim]Tip: Install the 'github/gh-stack' extension "
                "to automatically link PRs into a stack!\n"
                "    Run: gh extension install github/gh-stack[/dim]"
            )

    _print_final_summary(
        edits,
        creates,
        skipped_branches,
        pr_state,
        ui,
        stack_branches=ordered if stack_linked else None,
    )

    return success
