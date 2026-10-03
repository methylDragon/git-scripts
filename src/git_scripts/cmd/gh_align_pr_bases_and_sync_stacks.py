"""Command logic for git-gh-align-pr-bases-and-sync-stacks."""

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass

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
    sort_branches_bottom_to_top,
)
from git_scripts.models import RemotePushParityResult
from git_scripts.ui import UI

_PR_TEMPLATE_DIRS = (".github", "", "docs")
_PR_TEMPLATE_NAMES = ("pull_request_template.md", "pull_request_template")


@dataclass(frozen=True)
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


def _read_utf8_file(path: str) -> str:
    """Reads a UTF-8 file from disk, or returns an empty string on error."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _pick_subdir_template_name(names: Sequence[str]) -> str | None:
    """Picks default.md or a single .md file inside PULL_REQUEST_TEMPLATE/."""
    md_by_lower = {
        name.lower(): name for name in names if name.lower().endswith(".md")
    }
    if "default.md" in md_by_lower:
        return md_by_lower["default.md"]
    if len(md_by_lower) == 1:
        return next(iter(md_by_lower.values()))
    return None


def _find_template_in_workdir_dir(dir_path: str) -> str:
    """Searches a single directory on disk for a PR template file or subdir."""
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return ""

    files_by_lower = {
        e.lower(): e
        for e in entries
        if os.path.isfile(os.path.join(dir_path, e))
    }
    for target in _PR_TEMPLATE_NAMES:
        matched_file = files_by_lower.get(target)
        if matched_file:
            return _read_utf8_file(os.path.join(dir_path, matched_file))

    dirs_by_lower = {
        e.lower(): e
        for e in entries
        if os.path.isdir(os.path.join(dir_path, e))
    }
    subdir_name = dirs_by_lower.get("pull_request_template")
    if not subdir_name:
        return ""

    subdir_path = os.path.join(dir_path, subdir_name)
    try:
        sub_entries = [
            e
            for e in os.listdir(subdir_path)
            if os.path.isfile(os.path.join(subdir_path, e))
        ]
    except OSError:
        return ""

    chosen = _pick_subdir_template_name(sub_entries)
    return _read_utf8_file(os.path.join(subdir_path, chosen)) if chosen else ""


def _find_template_in_workdir(repo_path: str) -> str:
    """Searches GitHub PR template locations in the working tree."""
    if not repo_path or not os.path.isdir(repo_path):
        return ""
    for rel_dir in _PR_TEMPLATE_DIRS:
        dir_path = os.path.join(repo_path, rel_dir) if rel_dir else repo_path
        content = _find_template_in_workdir_dir(dir_path)
        if content:
            return content
    return ""


def _find_sub_tree_case_insensitive(
    tree: pygit2.Tree, target_name: str
) -> pygit2.Tree | None:
    """Finds a subtree inside a pygit2.Tree using case-insensitive matching."""
    target_lower = target_name.lower()
    for entry in tree:
        if (
            entry.name
            and entry.name.lower() == target_lower
            and isinstance(entry, pygit2.Tree)
        ):
            return entry
    return None


def _find_template_in_tree_dir(dir_tree: pygit2.Tree) -> str:
    """Searches a single pygit2.Tree directory for a PR template blob."""
    blobs_by_lower = {
        entry.name.lower(): entry
        for entry in dir_tree
        if entry.name and isinstance(entry, pygit2.Blob)
    }
    for target in _PR_TEMPLATE_NAMES:
        blob = blobs_by_lower.get(target)
        if blob is not None and isinstance(blob.data, bytes):
            return blob.data.decode("utf-8", errors="replace")

    sub_tree = _find_sub_tree_case_insensitive(
        dir_tree, "pull_request_template"
    )
    if sub_tree is None:
        return ""

    sub_blobs = {
        entry.name: entry
        for entry in sub_tree
        if entry.name and isinstance(entry, pygit2.Blob)
    }
    chosen = _pick_subdir_template_name(list(sub_blobs))
    if chosen and isinstance(sub_blobs[chosen].data, bytes):
        return sub_blobs[chosen].data.decode("utf-8", errors="replace")
    return ""


def _try_revparse(repo: pygit2.Repository, ref: str) -> pygit2.Object | None:
    """Resolves a Git revision, returning None if the ref does not exist."""
    try:
        return repo.revparse_single(ref)
    except (KeyError, ValueError, TypeError, pygit2.GitError):
        return None


def _find_template_in_git_tree(
    repo: pygit2.Repository, ref_names: Sequence[str]
) -> str:
    """Searches commit trees for a PR template when missing from workdir."""
    for ref in ref_names:
        commit = _try_revparse(repo, ref)
        root_tree = getattr(commit, "tree", None)
        if not isinstance(root_tree, pygit2.Tree):
            continue
        for rel_dir in _PR_TEMPLATE_DIRS:
            target_tree = (
                _find_sub_tree_case_insensitive(root_tree, rel_dir)
                if rel_dir
                else root_tree
            )
            if target_tree is None:
                continue
            content = _find_template_in_tree_dir(target_tree)
            if content:
                return content
    return ""


def _resolve_repo_workdir(repo: pygit2.Repository) -> str:
    """Returns the working directory path for a repository when available."""
    workdir = getattr(repo, "workdir", None)
    if isinstance(workdir, str) and workdir:
        return workdir
    repo_path = getattr(repo, "path", "")
    if not isinstance(repo_path, str):
        return ""
    return repo_path.replace(".git/", "")


def _get_pr_template(
    repo_path: str,
    repo: pygit2.Repository | None = None,
    ref_names: Sequence[str] = (),
) -> str:
    """Attempts to find and read a GitHub PR template from the repository."""
    content = _find_template_in_workdir(repo_path)
    if content or repo is None:
        return content
    return _find_template_in_git_tree(repo, ref_names)


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


def _resolve_base_commits(
    repo: pygit2.Repository,
    base: str,
    remote: str = "origin",
) -> list[pygit2.Object]:
    """Resolves commit objects to hide when walking commits ahead of base."""
    refs = (f"refs/remotes/{remote}/{base}", base)
    return [c for ref in refs if (c := _try_revparse(repo, ref)) is not None]


def _compute_pr_metadata(
    repo: pygit2.Repository,
    branch: str,
    base: str,
    template: str,
    remote: str = "origin",
) -> tuple[str, str]:
    """Computes the PR title and description based on commits ahead of base.

    1 commit: title=commit summary, desc=commit body.
    >1 commit: title=humanized branch name, desc=template (or blank).
    """
    branch_commit = _try_revparse(repo, branch)
    if branch_commit is None:
        # Fallback if something is detached or missing
        return _humanize_branch_name(branch), template

    base_commits = _resolve_base_commits(repo, base, remote=remote)
    if not base_commits:
        return _humanize_branch_name(branch), template

    walker = repo.walk(branch_commit.id, pygit2.enums.SortMode.TOPOLOGICAL)
    for base_commit in base_commits:
        walker.hide(base_commit.id)

    commits = list(walker)

    if len(commits) == 1:
        commit = commits[0]
        msg = commit.message.strip()
        lines = msg.split("\n", 1)
        title = lines[0].strip()
        description = lines[1].strip() if len(lines) > 1 else ""
        if template:
            description = (
                f"{description}\n\n{template}" if description else template
            )
        return title, description
    return _humanize_branch_name(branch), template


def _resolve_expected_pr_base(
    branch: str,
    parent_map: dict[str, str | None],
    pr_state: dict[str, GitHubPr],
    target_trunk: str,
    create_missing: bool,
) -> tuple[str, str]:
    curr_ancestor = parent_map.get(branch)
    skipped = False
    while (
        not create_missing
        and curr_ancestor is not None
        and curr_ancestor not in pr_state
    ):
        curr_ancestor = parent_map.get(curr_ancestor)
        skipped = True

    expected_base = curr_ancestor if curr_ancestor else target_trunk
    reason = (
        "Matches nearest ancestor with an open PR"
        if skipped
        else "Matches local topology"
    )
    return expected_base, reason


def calculate_pr_actions(
    repo: pygit2.Repository,
    branches: set[str],
    pr_state: dict[str, GitHubPr],
    target_trunk: str = "main",
    create_missing: bool = False,
    parent_map: dict[str, str | None] | None = None,
    remote: str = "origin",
) -> tuple[list[PrEditAction], list[PrCreateAction]]:
    """Map local topology to required PR edits and creations."""
    if parent_map is None:
        parent_map = {
            b: get_parent_branch(repo, b, branches) for b in sorted(branches)
        }

    edits = []
    creates = []

    workdir = _resolve_repo_workdir(repo)
    template_refs = (
        f"refs/remotes/{remote}/{target_trunk}",
        target_trunk,
        "HEAD",
        *sorted(branches),
    )
    pr_template = _get_pr_template(workdir, repo=repo, ref_names=template_refs)

    for branch in sorted(branches):
        if branch not in pr_state:
            parent = parent_map.get(branch)
            base = parent if parent else target_trunk
            title, description = _compute_pr_metadata(
                repo,
                branch,
                base,
                pr_template,
                remote=remote,
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
        expected_base, reason = _resolve_expected_pr_base(
            branch, parent_map, pr_state, target_trunk, create_missing
        )
        if current_base != expected_base:
            edits.append(
                PrEditAction(
                    branch=branch,
                    old_base=current_base,
                    new_base=expected_base,
                    reason=reason,
                    url=pr_state[branch].url,
                    pr_number=str(pr_state[branch].number),
                )
            )

    return edits, creates


def _group_into_stacks(
    repo: pygit2.Repository,
    branches: set[str],
    parent_map: dict[str, str | None] | None = None,
) -> dict[str, list[str]]:
    """Groups branches into distinct topological stacks."""
    if parent_map is None:
        parent_map = {
            b: get_parent_branch(repo, b, branches) for b in sorted(branches)
        }
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
                time.sleep(1)
                if not os.environ.get("GIT_SCRIPTS_DEMO"):
                    url = gh_pr_create(
                        repo_path,
                        action.branch,
                        action.base,
                        title=action.title,
                        body=action.description,
                    )
                else:
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
) -> tuple[bool, list[str] | None, dict[str, str | None]]:
    parent_map = {
        b: get_parent_branch(repo, b, selected_branches)
        for b in sorted(selected_branches)
    }
    ordered = sort_branches_bottom_to_top(selected_branches, parent_map)
    stacks = _group_into_stacks(repo, selected_branches, parent_map)

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
            return False, None, parent_map

        ok, broken_branch = check_stack_continuity(repo, stack_branches)
        if not ok:
            ui.print(
                "[red]❌ Validation Failed: Stack continuity broken.[/red]\n"
                f"[yellow]Branch '{broken_branch}' is not a valid descendant "
                "of its base branch.\n"
                "Action required: Perform a cascading rebase to ensure a "
                "strictly linear commit history across the stack.[/yellow]"
            )
            return False, None, parent_map

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
        return False, None, parent_map

    if parity.unpushed_branches:
        if not _prompt_and_push_unpushed_branches(
            parity, repo_path, ui, remote=remote
        ):
            return False, None, parent_map

    return True, ordered, parent_map


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

    pr_number = _find_first_stack_pr_number(ordered, pr_state)
    if pr_number:
        _sync_gh_stack_checkout(repo_path, pr_number, ui)

    _sync_gh_stack_unstack(repo_path, ui)

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
) -> tuple[bool, bool]:
    if not edits and not creates:
        msg = "All GitHub PR bases are already aligned with local topology!"
        ui.print(f"\n✨  {msg}")
        return False, True

    if not ui.auto_yes and not ui.confirm(
        "\n❓  Apply these changes to GitHub?"
    ):
        ui.print("❌  Operation cancelled.")
        return True, True

    success_edits = _execute_edits(edits, repo_path, ui)
    success_creates = _execute_creates(creates, repo_path, ui)
    success = success_edits and success_creates

    _update_pr_state_from_creates(creates, pr_state)

    if success:
        ui.print("\n🎉  All PR operations completed successfully!")
    else:
        ui.print("\n⚠️   Finished with some errors.")
    return False, success


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

    ok, _, parent_map = _verify_topology(
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

    edits, creates = calculate_pr_actions(
        repo,
        selected_branches,
        pr_state,
        target_trunk=target,
        create_missing=create_missing,
        parent_map=parent_map,
        remote=resolved_remote,
    )

    _print_edits(edits, ui)
    creates = _prompt_creates(creates, create_missing, ui)

    action_branches = {a.branch for a in edits} | {c.branch for c in creates}
    skipped_branches = selected_branches - action_branches

    cancelled, success = _apply_pr_actions(
        edits, creates, pr_state, repo_path, ui
    )
    if cancelled:
        return True

    linked_branches: list[str] = []
    if success and len(selected_branches) > 1:
        stacks = _group_into_stacks(repo, selected_branches, parent_map)
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
        stack_branches=linked_branches or None,
    )
    return success
