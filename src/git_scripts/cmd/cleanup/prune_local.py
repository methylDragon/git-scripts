"""Core logic for the git cleanup branches local (git-prune-local) command."""

import time

import pygit2
from rich.panel import Panel

from git_scripts.cmd.shared import (
    BranchProgressTracker,
    select_branches_to_delete,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.parallel import analyze_branches_in_parallel
from git_scripts.git.reads import get_repo, is_obsolete
from git_scripts.models import LocalPruneResult
from git_scripts.ui import UI


def _get_worktree_branches(repo_path: str) -> set[str]:
    """Retrieves a set of local branches currently checked out in worktrees."""
    try:
        worktrees_out = run_cmd(
            ["git", "worktree", "list", "--porcelain"], cwd=repo_path
        )
        worktree_branches = set()
        for line in worktrees_out.splitlines():
            if line.startswith("branch refs/heads/"):
                worktree_branches.add(line[len("branch refs/heads/") :])
        return worktree_branches
    except GitExecutionError:
        return set()


def _get_gone_branches(
    repo_path: str,
    worktree_branches: set[str],
    prefix: str | None = None,
) -> list[str]:
    """Finds local branches whose upstream tracking branches are gone."""
    try:
        branch_vv_out = run_cmd(["git", "branch", "-vv"], cwd=repo_path)
    except GitExecutionError:
        return []

    branches_to_prune = []
    for line in branch_vv_out.splitlines():
        if ": gone]" not in line:
            continue
        parts = line.strip().split()
        branch = parts[1] if parts[0] in ("*", "+") else parts[0]
        if prefix is not None and not branch.startswith(prefix):
            continue
        if branch not in worktree_branches:
            branches_to_prune.append(branch)
    return branches_to_prune


def _has_upstream_tracking(repo: pygit2.Repository, branch_name: str) -> bool:
    """Returns True if the local branch has upstream tracking configured."""
    if branch_name not in repo.branches.local:
        return False
    if (
        f"branch.{branch_name}.remote" in repo.config
        or f"branch.{branch_name}.merge" in repo.config
    ):
        return True
    try:
        return repo.branches.local[branch_name].upstream is not None
    except (KeyError, pygit2.GitError):
        # Upstream is configured in .git/config, but its remote ref is gone.
        return True


def _get_protected_branches(
    repo: pygit2.Repository,
    target: str,
    worktree_branches: set[str],
    gone_branches: list[str],
) -> set[str]:
    """Returns local branches excluded from no-upstream pruning."""
    protected = set(worktree_branches) | set(gone_branches) | {target}
    if not repo.head_is_unborn and not repo.head_is_detached:
        protected.add(repo.head.shorthand)
    return protected


def _get_untracked_local_branches(
    repo: pygit2.Repository,
    protected_branches: set[str],
    prefix: str | None = None,
) -> list[str]:
    """Returns local branches that have no upstream tracking configured."""
    untracked = []
    for branch_name in sorted(repo.branches.local):
        if branch_name in protected_branches:
            continue
        if prefix is not None and not branch_name.startswith(prefix):
            continue
        if not _has_upstream_tracking(repo, branch_name):
            untracked.append(branch_name)
    return untracked


def _resolve_target_refs(repo: pygit2.Repository, target: str) -> list[str]:
    """Resolves valid remote and local refs for the target branch."""
    candidates = (
        f"refs/remotes/origin/{target}",
        f"refs/heads/{target}",
    )
    target_refs: list[str] = []
    seen_oids: set[pygit2.Oid] = set()
    for ref_name in candidates:
        try:
            commit_oid = repo.revparse_single(ref_name).id
        except (KeyError, ValueError):
            continue
        if commit_oid not in seen_oids:
            seen_oids.add(commit_oid)
            target_refs.append(ref_name)
    return target_refs


def _is_branch_obsolete_in_targets(
    repo_path: str, branch_name: str, target_refs: list[str]
) -> bool:
    """Checks if a local branch is obsolete against any resolved target."""
    local_repo = get_repo(repo_path)
    commit_id = local_repo.revparse_single(f"refs/heads/{branch_name}").id
    return any(
        is_obsolete(local_repo, commit_id, target_ref)
        for target_ref in target_refs
    )


def _classify_untracked_branches(
    repo_path: str,
    repo: pygit2.Repository,
    untracked_branches: list[str],
    target: str,
    ui: UI,
) -> tuple[list[str], list[str]]:
    """Splits untracked local branches into obsolete and unmerged buckets."""
    if not untracked_branches:
        return [], []

    target_refs = _resolve_target_refs(repo, target)
    if not target_refs:
        return [], list(untracked_branches)

    ui.print(
        "[dim]🔍  Scanning untracked local branches for obsolescence...[/dim]"
    )
    start_time = time.time()

    with BranchProgressTracker(ui, "Analyzing obsolescence") as tracker:
        results = analyze_branches_in_parallel(
            repo_path=repo_path,
            branches=untracked_branches,
            target_ref=target_refs[0],
            analyze_fn=lambda b: _is_branch_obsolete_in_targets(
                repo_path, b, target_refs
            ),
            on_start=tracker.on_start,
            on_progress=tracker.on_progress,
        )

    obsolete_untracked = []
    unmerged_untracked = []
    for branch_name in untracked_branches:
        if results.get(branch_name, False):
            obsolete_untracked.append(branch_name)
        else:
            unmerged_untracked.append(branch_name)

    elapsed = time.time() - start_time
    ui.print(
        f"  [dim]⏱️  Local obsolescence scan completed in {elapsed:.2f}s[/dim]"
    )
    return obsolete_untracked, unmerged_untracked


def _find_local_branches_to_prune(
    repo_path: str,
    target: str,
    also_prune_no_upstream: bool,
    ui: UI,
    prefix: str | None = None,
) -> LocalPruneResult:
    """Discovers gone and untracked local branches eligible for pruning."""
    worktree_branches = _get_worktree_branches(repo_path)
    gone_branches = _get_gone_branches(
        repo_path, worktree_branches, prefix=prefix
    )
    if not also_prune_no_upstream:
        return LocalPruneResult(
            orphaned_branches=gone_branches,
            unmerged_no_upstream_branches=[],
        )

    repo = get_repo(repo_path)
    protected = _get_protected_branches(
        repo, target, worktree_branches, gone_branches
    )
    untracked_branches = _get_untracked_local_branches(
        repo, protected, prefix=prefix
    )
    obsolete_untracked, unmerged_untracked = _classify_untracked_branches(
        repo_path, repo, untracked_branches, target, ui
    )
    return LocalPruneResult(
        orphaned_branches=gone_branches + obsolete_untracked,
        unmerged_no_upstream_branches=unmerged_untracked,
    )


def _print_prune_local_summary(prune_result: LocalPruneResult, ui: UI) -> None:
    """Prints panels summarizing orphaned and unmerged local branches."""
    orphaned = prune_result.orphaned_branches
    unmerged = prune_result.unmerged_no_upstream_branches

    if orphaned:
        branch_list = "\n".join(f"  - [cyan]{b}[/cyan]" for b in orphaned)
        ui.print(
            Panel(
                branch_list,
                title=(
                    f"[bold yellow]Found {len(orphaned)} "
                    "orphaned local branches[/bold yellow]"
                ),
                border_style="yellow",
                expand=False,
            )
        )

    if unmerged:
        branch_list = "\n".join(f"  - [red]{b}[/red]" for b in unmerged)
        ui.print(
            Panel(
                branch_list,
                title=(
                    f"[bold red]Found {len(unmerged)} "
                    "unmerged branches lacking upstream tracking[/bold red]"
                ),
                border_style="red",
                expand=False,
            )
        )


def _prompt_and_delete_local_branches(
    prune_result: LocalPruneResult, ui: UI, repo_path: str
) -> bool:
    """Prompts the user per bucket and deletes selected local branches."""
    orphaned = prune_result.orphaned_branches
    unmerged = prune_result.unmerged_no_upstream_branches
    to_delete: list[str] = []

    if orphaned:
        orphaned_label = ui.pluralize(len(orphaned), "orphaned local branch")
        orphaned_prompt = f"❓  Delete the {orphaned_label}?"
        to_delete.extend(
            select_branches_to_delete(
                orphaned,
                orphaned_prompt,
                "Select orphaned local branches to delete:",
                ui,
            )
        )

    if unmerged:
        unmerged_prompt = (
            f"⚠️  Delete {len(unmerged)} unmerged local branches "
            "(no upstream tracking)?"
        )
        to_delete.extend(
            select_branches_to_delete(
                unmerged,
                unmerged_prompt,
                "Select unmerged local branches to delete:",
                ui,
            )
        )

    if not to_delete:
        return True

    ui.print("\n🗑️  Pruning branches...")
    try:
        cmd = ["git", "branch", "-D"] + to_delete
        out = run_cmd(cmd, cwd=repo_path)
        ui.print(out)
        return True
    except GitExecutionError as e:
        ui.print(f"[red]Failed to prune branches: {e}[/red]")
        return False


def execute_prune_local(
    repo_path: str,
    dry_run: bool = False,
    also_prune_no_upstream: bool = False,
    target: str = "main",
    prefix: str | None = None,
    ui: UI | None = None,
) -> bool:
    """Prunes local branches that no longer exist on the remote."""
    if ui is None:
        ui = UI()

    if prefix is not None and not prefix.strip():
        ui.print("❌  Error: <prefix> cannot be empty.")
        return False

    if dry_run:
        ui.print("Running git-prune-local in dry-run mode...")

    ui.print("[dim]🔄  Fetching origin --prune...[/dim]")
    try:
        run_cmd(["git", "fetch", "-p"], cwd=repo_path)
    except GitExecutionError:
        pass

    prune_result = _find_local_branches_to_prune(
        repo_path, target, also_prune_no_upstream, ui, prefix=prefix
    )

    if (
        not prune_result.orphaned_branches
        and not prune_result.unmerged_no_upstream_branches
    ):
        ui.print("✅  No orphaned branches to prune.")
        return True

    _print_prune_local_summary(prune_result, ui)

    if dry_run:
        ui.print("\n📦  [Dry Run] No branches would be deleted.")
        return True

    return _prompt_and_delete_local_branches(prune_result, ui, repo_path)
