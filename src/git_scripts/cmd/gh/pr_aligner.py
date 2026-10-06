"""Orchestrates GitHub PR base alignment and stack synchronization."""

import os
import time

import pygit2
import questionary
from rich.panel import Panel

from git_scripts.cmd.shared import resolve_branches_to_push
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
from git_scripts.gh.pr_planner import (
    PrCreateAction,
    PrEditAction,
    calculate_pr_actions,
    reconcile_edits_for_uncreated_prs,
)
from git_scripts.git.core import run_cmd
from git_scripts.git.reads import get_repo
from git_scripts.git.remote import (
    get_configured_remotes,
    get_default_remote,
    push_branches,
)
from git_scripts.git.topology import (
    check_remote_push_parity,
    check_remote_trunk_ancestry,
    check_stack_continuity,
    find_linear_stack,
    get_parent_branch,
    group_into_stacks,
    sort_branches_bottom_to_top,
)
from git_scripts.models import RemotePushParityResult
from git_scripts.ui import UI


def _handle_interactive_selection(
    repo: pygit2.Repository,
    branches: set[str],
    ui: UI,
    parent_map: dict[str, str | None] | None = None,
) -> set[str]:
    stacks = group_into_stacks(repo, branches, parent_map=parent_map)
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


def _resolve_prefix_branches(
    repo: pygit2.Repository,
    prefix: str,
    matched: set[str],
    head: str | None,
    current_stack_only: bool,
    all_matching: bool,
    interactive: bool,
    target: str,
    ui: UI,
) -> set[str] | None:
    if (
        head in matched
        and not current_stack_only
        and not all_matching
        and not interactive
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
        match action:
            case "Cancel" | None:
                return set()
            case "Current stack only":
                current_stack_only = True
            case "Select which stacks to align":
                interactive = True
            case _:
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
        return find_linear_stack(repo, head, matched, stop_at=target)
    return matched


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
        matched = {
            b
            for b in all_local_branches
            if b.startswith(prefix) and b != target
        }
        if not matched:
            ui.print(f"❌  No branches found matching prefix '{prefix}'")
            return None
        return _resolve_prefix_branches(
            repo,
            prefix,
            matched,
            head,
            current_stack_only,
            all_matching,
            interactive,
            target,
            ui,
        )

    if interactive:
        return _handle_interactive_selection(
            repo, all_local_branches - {target}, ui
        )

    if head == target or not head:
        ui.print(f"❌  Cannot align: HEAD is on {head or 'detached'}.")
        return None
    return find_linear_stack(repo, head, all_local_branches, stop_at=target)


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

    title_str = (
        "[bold cyan]Branch Summary "
        f"({ui.pluralize(len(selected_branches), 'branch')})[/bold cyan]"
    )
    ui.print(
        Panel(
            summary_text.rstrip(),
            title=title_str,
            border_style="cyan",
            expand=False,
        )
    )


def _print_create_actions(actions: list[PrCreateAction], ui: UI) -> None:
    for action in actions:
        ui.print(
            f"  - [yellow]{action.branch}[/yellow] "
            f"([dim]base:[/dim] [green]{action.base}[/green]) - "
            f'[cyan]"{action.title}"[/cyan]'
        )


def _prompt_creates(
    creates: list[PrCreateAction], create_missing: bool, ui: UI
) -> list[PrCreateAction]:
    if not creates:
        return []

    creates.sort(key=lambda c: c.branch)

    ui.print("\n[bold green]Potential PR Creations (Drafts):[/bold green]")
    if ui.auto_yes:
        if create_missing:
            _print_create_actions(creates, ui)
            return creates
        return []

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
    _print_create_actions(filtered, ui)
    return filtered


def _execute_edits(edits: list[PrEditAction], repo_path: str, ui: UI) -> bool:
    success = True
    if edits:
        ui.print("\n🚀  Updating PR bases via GitHub API...")
        for action in edits:
            try:
                if not os.environ.get("GIT_SCRIPTS_DEMO"):
                    gh_pr_edit(
                        repo_path,
                        action.branch,
                        action.new_base,
                        action.pr_number,
                    )
                else:
                    time.sleep(0.5)
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
                if not os.environ.get("GIT_SCRIPTS_DEMO"):
                    url = gh_pr_create(
                        repo_path,
                        action.branch,
                        action.base,
                        title=action.title,
                        body=action.description,
                    )
                else:
                    time.sleep(1)
                    b_id = action.branch.split("/")[-1]
                    url = f"https://github.com/demo/pull/{b_id}"
                action.url = url
                ui.print(
                    "  ✅  Created Draft PR for "
                    f"[yellow]{action.branch}[/yellow]"
                    f" ➔ [green]{action.base}[/green]\n"
                    f"      [dim]🔗  {url}[/dim]"
                )
            except GhExecutionError as e:
                err_msg = str(e)
                ui.print(
                    "  ❌  Failed to create PR for "
                    f"[yellow]{action.branch}[/yellow]: "
                    f"[dim]{err_msg.strip()}[/dim]"
                )
                success = False
    return success


def _format_summary_section(
    header: str, items: list[tuple[str, str | None]]
) -> str:
    if not items:
        return ""
    lines = [header]
    for branch, url in items:
        lines.append(f"      - [yellow]{branch}[/yellow]")
        if url:
            lines.append(f"        [dim]🔗  {url}[/dim]")
    return "\n".join(lines) + "\n"


def _print_final_summary(
    edits: list[PrEditAction],
    creates: list[PrCreateAction],
    skipped_branches: set[str],
    pr_state: dict[str, GitHubPr],
    ui: UI,
    stack_branches: list[str] | None = None,
) -> None:
    edit_plural = "PR" if len(edits) == 1 else "PRs"
    create_plural = "PR" if len(creates) == 1 else "PRs"
    skip_plural = "branch" if len(skipped_branches) == 1 else "branches"

    sections = [
        _format_summary_section(
            f"✅  Aligned base for [green]{len(edits)}[/green] {edit_plural}:",
            [(a.branch, a.url) for a in edits],
        ),
        _format_summary_section(
            f"✅  Created [green]{len(creates)}[/green] new {create_plural}:",
            [(c.branch, c.url) for c in creates],
        ),
        _format_summary_section(
            "🔗  Synced GitHub stack for "
            f"[green]{len(stack_branches or [])}[/green] branches:",
            [
                (b, pr_state[b].url if b in pr_state else None)
                for b in (stack_branches or [])
            ],
        ),
        _format_summary_section(
            "⏭️   Skipped base alignment for "
            f"[yellow]{len(skipped_branches)}[/yellow] {skip_plural}:",
            [
                (b, pr_state[b].url if b in pr_state else None)
                for b in sorted(skipped_branches)
            ],
        ),
    ]
    final_summary = "".join(sections)
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


def _prompt_and_push_unpushed_branches(
    parity: RemotePushParityResult,
    repo_path: str,
    ui: UI,
    remote: str = "origin",
) -> bool:
    unpushed = list(parity.unpushed_branches)
    diverged = set(parity.diverged_branches)
    ui.print(
        "\n[yellow]⚠️  Found "
        f"{ui.pluralize(len(unpushed), 'unpushed branch')} "
        f"that must be pushed to {remote} before aligning PRs:[/yellow]"
    )
    for branch in unpushed:
        suffix = (
            " [dim](rebased/diverged, requires --force-with-lease)[/dim]"
            if branch in diverged
            else ""
        )
        ui.print(f"  - [yellow]{branch}[/yellow]{suffix}")

    branches_to_push = resolve_branches_to_push(
        branches=unpushed,
        ui=ui,
        prompt_title=(
            f"Push {ui.pluralize(len(unpushed), 'unpushed branch')} "
            f"to {remote} before aligning PRs?"
        ),
    )
    if branches_to_push and not os.environ.get("GIT_SCRIPTS_DEMO"):
        push_opts = (
            ["--force-with-lease"]
            if (set(branches_to_push) & diverged)
            else []
        )
        if not push_branches(
            branches=branches_to_push,
            options=push_opts,
            repo_path=repo_path,
            remote=remote,
        ):
            ui.print(f"[red]❌ Failed to push branches to {remote}.[/red]")
            return False

    pushed_set = set(branches_to_push or [])
    remaining = [b for b in unpushed if b not in pushed_set]
    if remaining:
        ui.print(
            "[red]❌ Validation Failed: Unpushed local changes.[/red]\n"
            f"[yellow]Branch '{remaining[0]}' has local commits that are not "
            "pushed to the remote.\n"
            "Action required: Push all branches in the stack before "
            "aligning PR bases to prevent GitHub API rejections.[/yellow]"
        )
        return False

    return True


def _resolve_remote(
    repo: pygit2.Repository, remote: str | None, ui: UI
) -> tuple[bool, str | None]:
    """Resolves target remote from flag, single remote, or interactive prompt.

    Returns (ok, resolved_remote). When the user cancels the interactive
    prompt, returns (True, None) so the caller can exit cleanly with True.
    """
    remotes = get_configured_remotes(repo)

    if remote:
        if remotes and remote not in remotes:
            available = ", ".join(remotes)
            ui.print(
                f"❌  Remote '{remote}' not found (available: {available})."
            )
            return False, None
        return True, remote

    if not remotes:
        return True, "origin"

    if len(remotes) == 1:
        return True, remotes[0]

    default_remote = get_default_remote(repo, remotes)
    chosen = ui.ask_choice(
        "Multiple remotes detected. Which remote do you want to align to?",
        choices=remotes,
        default=default_remote,
    )
    if chosen is None:
        ui.print("❌  Operation cancelled.")
        return True, None
    return True, chosen


def _verify_topology(
    repo: pygit2.Repository,
    selected_branches: set[str],
    target: str,
    ui: UI,
    repo_path: str = ".",
    remote: str = "origin",
) -> tuple[
    bool,
    list[str] | None,
    dict[str, str | None],
    dict[str, list[str]],
]:
    parent_map = {
        b: get_parent_branch(repo, b, selected_branches)
        for b in sorted(selected_branches)
    }
    ordered = sort_branches_bottom_to_top(selected_branches, parent_map)
    stacks = group_into_stacks(repo, selected_branches, parent_map)

    for stack_branches in stacks.values():
        if not stack_branches:
            continue
        bottom_branch = stack_branches[0]
        if not check_remote_trunk_ancestry(
            repo, bottom_branch, target, remote=remote
        ):
            ui.print(
                "[red]❌ Validation Failed: Remote trunk divergence.[/red]\n"
                "[yellow]Your local stack is not strictly ahead of "
                f"'{target}'. The remote base was likely updated.\n"
                "Action required: Fetch the latest changes and rebase your "
                f"stack onto '{target}' before aligning PRs.[/yellow]"
            )
            return False, None, parent_map, stacks

        ok, broken_branch = check_stack_continuity(repo, stack_branches)
        if not ok:
            ui.print(
                "[red]❌ Validation Failed: Stack continuity broken.[/red]\n"
                f"[yellow]Branch '{broken_branch}' is not a valid descendant "
                "of its base branch.\n"
                "Action required: Perform a cascading rebase to ensure a "
                "strictly linear commit history across the stack.[/yellow]"
            )
            return False, None, parent_map, stacks

    parity = check_remote_push_parity(repo, ordered, remote=remote)
    if parity.behind_remote_branches:
        behind_branch = parity.behind_remote_branches[0]
        ui.print(
            "[red]❌ Validation Failed: Remote branch ahead.[/red]\n"
            f"[yellow]Branch '{behind_branch}' is behind its remote tracking "
            "branch.\n"
            "Action required: Pull or rebase onto the latest remote changes "
            "before aligning PR bases.[/yellow]"
        )
        return False, None, parent_map, stacks

    if parity.unpushed_branches:
        if not _prompt_and_push_unpushed_branches(
            parity, repo_path, ui, remote=remote
        ):
            return False, None, parent_map, stacks

    return True, ordered, parent_map, stacks


def _get_checked_out_branch(repo_path: str) -> str | None:
    """Returns the checked-out local branch shorthand if on a branch."""
    try:
        repo = get_repo(repo_path)
        if getattr(repo, "head_is_detached", False):
            return None
        shorthand = getattr(repo.head, "shorthand", None)
        return shorthand if isinstance(shorthand, str) and shorthand else None
    except (pygit2.GitError, KeyError, OSError, ValueError):
        return None


def _restore_checked_out_branch(
    repo_path: str, start_branch: str | None
) -> None:
    """Restores start_branch if gh stack checkout switched the working tree."""
    if not start_branch or os.environ.get("GIT_SCRIPTS_DEMO"):
        return
    current_branch = _get_checked_out_branch(repo_path)
    if current_branch and current_branch != start_branch:
        run_cmd(["git", "checkout", start_branch], cwd=repo_path, check=False)


def _sync_gh_stack_checkout(repo_path: str, pr_number: str, ui: UI) -> None:
    ui.print(f"\n🔄  Checking out PR #{pr_number} to ensure local tracking...")
    try:
        if not os.environ.get("GIT_SCRIPTS_DEMO"):
            gh_stack_checkout(repo_path, pr_number)
    except GhExecutionError as e:
        if "not part of a stack on GitHub" in str(e):
            ui.print(
                "  ℹ️   PR is not part of a stack on GitHub (skipping checkout)"
            )
        else:
            ui.print(f"  ⚠️   Checkout failed: [dim]{str(e)}[/dim]")


def _sync_gh_stack_unstack(repo_path: str, ui: UI) -> None:
    ui.print(
        "\n🗑️  Unstacking current remote stack state to ensure "
        "synchronization..."
    )
    try:
        if not os.environ.get("GIT_SCRIPTS_DEMO"):
            gh_stack_unstack(repo_path)
        ui.print("  ✅  Unstacked successfully!")
    except GhExecutionError as e:
        if "not part of a stack" in str(e):
            ui.print("  ✅  Unstacked successfully! (was not stacked)")
        else:
            ui.print(
                "  ⚠️   Unstack failed (might not be stacked): "
                f"[dim]{str(e)}[/dim]"
            )


def _update_pr_state_from_creates(
    creates: list[PrCreateAction], pr_state: dict[str, GitHubPr]
) -> None:
    for c in creates:
        if c.url:
            tail = c.url.rsplit("/", 1)[-1]
            pr_state[c.branch] = GitHubPr(
                headRefName=c.branch,
                baseRefName=c.base,
                url=c.url,
                number=int(tail) if tail.isdigit() else -1,
            )


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


def _find_first_stack_pr_number(
    ordered: list[str], pr_state: dict[str, GitHubPr]
) -> str | None:
    for branch in ordered:
        pr = pr_state.get(branch)
        if pr and pr.number > 0:
            return str(pr.number)
    return None


def _sync_gh_stack_link(
    repo_path: str,
    ordered: list[str],
    ui: UI,
    remote: str = "origin",
) -> bool:
    ui.print("\n🚀  Linking stack on GitHub...")
    try:
        if not os.environ.get("GIT_SCRIPTS_DEMO"):
            gh_stack_link(repo_path, ordered, remote=remote)
        ui.print("  ✅  Stack linked successfully!")
        return True
    except GhExecutionError as e:
        err_text = str(e).removeprefix("Failed to link stack: ")
        ui.print(
            f"  ❌  Failed to link stack: [dim]{err_text}[/dim]\n"
            "This usually happens if the base branch was updated "
            "on the remote. Please fetch, rebase your stack, "
            "push, and try again."
        )
        return False


def _sync_gh_stack(
    repo_path: str,
    ordered: list[str],
    pr_state: dict[str, GitHubPr],
    parent_map: dict[str, str | None],
    target: str,
    ui: UI,
    remote: str = "origin",
) -> bool:
    ui.print("\n[bold cyan]Stack Topology:[/bold cyan]")
    for idx, branch in enumerate(reversed(ordered)):
        stack_idx = len(ordered) - idx
        ui.print(f"({stack_idx}/{len(ordered)})  {branch}")

    if ordered:
        bottom_branch = ordered[0]
        base = parent_map.get(bottom_branch) or target
        ui.print(f"(base) {base}")

    if not ui.auto_yes and not ui.confirm(
        "\n🔗  Synchronize GitHub stack with local topology? "
        "(Unstacks and relinks via 'gh stack link')"
    ):
        return False

    start_branch = _get_checked_out_branch(repo_path)
    try:
        pr_number = _find_first_stack_pr_number(ordered, pr_state)
        if pr_number:
            _sync_gh_stack_checkout(repo_path, pr_number, ui)

        _sync_gh_stack_unstack(repo_path, ui)
        return _sync_gh_stack_link(repo_path, ordered, ui, remote=remote)
    finally:
        _restore_checked_out_branch(repo_path, start_branch)


def _sync_all_gh_stacks(
    repo_path: str,
    stacks: dict[str, list[str]],
    pr_state: dict[str, GitHubPr],
    parent_map: dict[str, str | None],
    target: str,
    ui: UI,
    remote: str = "origin",
) -> tuple[bool, list[str]]:
    if not check_gh_stack_installed():
        ui.print(
            "\n💡  [dim]Tip: Install the 'github/gh-stack' extension "
            "to automatically link PRs into a stack!\n"
            "    Run: gh extension install github/gh-stack[/dim]"
        )
        return True, []

    linked_branches: list[str] = []
    all_ok = True

    for stack_branches in stacks.values():
        linkable = [b for b in stack_branches if b in pr_state]
        if len(linkable) < 2:
            continue
        if _sync_gh_stack(
            repo_path,
            linkable,
            pr_state,
            parent_map,
            target,
            ui,
            remote=remote,
        ):
            linked_branches.extend(linkable)
        else:
            all_ok = False

    return all_ok, linked_branches


def _check_auth(ui: UI) -> bool:
    if os.environ.get("GIT_SCRIPTS_DEMO"):
        return True
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


def _apply_pr_actions(
    edits: list[PrEditAction],
    creates: list[PrCreateAction],
    pr_state: dict[str, GitHubPr],
    repo_path: str,
    ui: UI,
    planned_create_branches: set[str] | None = None,
    parent_map: dict[str, str | None] | None = None,
    target_trunk: str = "main",
) -> tuple[bool, bool, list[PrEditAction]]:
    if not edits and not creates:
        msg = "All GitHub PR bases are already aligned with local topology!"
        ui.print(f"\n✨  {msg}")
        return False, True, edits

    if not ui.auto_yes and not ui.confirm(
        "\n❓  Apply these changes to GitHub?"
    ):
        ui.print("❌  Operation cancelled.")
        return True, True, edits

    success_creates = _execute_creates(creates, repo_path, ui)
    _update_pr_state_from_creates(creates, pr_state)

    if planned_create_branches and parent_map is not None:
        uncreated = planned_create_branches - set(pr_state)
        edits = reconcile_edits_for_uncreated_prs(
            edits,
            uncreated,
            parent_map,
            pr_state,
            target_trunk=target_trunk,
        )

    success_edits = _execute_edits(edits, repo_path, ui)
    success = success_edits and success_creates

    if success:
        ui.print("\n🎉  All PR operations completed successfully!")
    else:
        ui.print("\n⚠️   Finished with some errors.")
    return False, success, edits


def _fetch_pr_state(repo_path: str, ui: UI) -> dict[str, GitHubPr]:
    ui.print("🔄  Fetching GitHub PR states...")
    if os.environ.get("GIT_SCRIPTS_DEMO"):
        return {
            "demo/d-e": GitHubPr(
                headRefName="demo/d-e",
                baseRefName="main",
                url="https://github.com/demo/pull/2",
                number=2,
            ),
            "demo/d": GitHubPr(
                headRefName="demo/d",
                baseRefName="main",
                url="https://github.com/demo/pull/1",
                number=1,
            ),
        }
    return get_open_prs(repo_path)


def _get_skipped_branches(
    selected_branches: set[str],
    edits: list[PrEditAction],
    creates: list[PrCreateAction],
) -> set[str]:
    action_branches = {a.branch for a in edits} | {c.branch for c in creates}
    return selected_branches - action_branches


def execute_align_pr_bases_and_sync_stacks(
    repo_path: str,
    prefix: str | None = None,
    target: str = "main",
    current_stack_only: bool = False,
    all_matching: bool = False,
    create_missing: bool = False,
    interactive: bool = False,
    remote: str | None = None,
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

    ok_remote, resolved_remote = _resolve_remote(repo, remote, ui)
    if not resolved_remote:
        return ok_remote

    ui.print(
        "🔍  Analyzing topology for "
        f"{ui.pluralize(len(selected_branches), 'branch')}..."
    )

    ok, _, parent_map, stacks = _verify_topology(
        repo,
        selected_branches,
        target,
        ui,
        repo_path=repo_path,
        remote=resolved_remote,
    )
    if not ok:
        return False

    pr_state = _fetch_pr_state(repo_path, ui)
    _print_branch_summary(selected_branches, pr_state, ui)

    edits, all_creates = calculate_pr_actions(
        repo,
        selected_branches,
        pr_state,
        target_trunk=target,
        create_missing=create_missing or not ui.auto_yes,
        parent_map=parent_map,
        remote=resolved_remote,
    )

    _print_edits(edits, ui)
    planned_create_branches = {c.branch for c in all_creates}
    creates = _prompt_creates(all_creates, create_missing, ui)

    cancelled, success, edits = _apply_pr_actions(
        edits,
        creates,
        pr_state,
        repo_path,
        ui,
        planned_create_branches=planned_create_branches,
        parent_map=parent_map,
        target_trunk=target,
    )
    if cancelled:
        return True

    skipped_branches = _get_skipped_branches(selected_branches, edits, creates)

    linked_branches: list[str] = []
    if success and len(selected_branches) > 1:
        success, linked_branches = _sync_all_gh_stacks(
            repo_path,
            stacks,
            pr_state,
            parent_map,
            target,
            ui,
            remote=resolved_remote,
        )

    _print_final_summary(
        edits,
        creates,
        skipped_branches,
        pr_state,
        ui,
        stack_branches=linked_branches,
    )
    return success
