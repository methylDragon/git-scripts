"""Core logic for the git prefix rebase (git-rebase-prefix) command."""

import pygit2

from git_scripts.cmd.rebase.rebase_orchestrator import execute_batch_rebase
from git_scripts.cmd.shared import restore_branch, ui_update_target
from git_scripts.ui import UI


def _find_matching_branches(
    repo: pygit2.Repository, prefix: str, target: str
) -> list[str]:
    """Finds all local branches matching the prefix."""
    all_branches = []
    for ref in repo.references:
        if ref.startswith(f"refs/heads/{prefix}"):
            short_name = ref[len("refs/heads/") :]
            if short_name != target:
                all_branches.append(short_name)
    return all_branches


def execute_rebase_prefix(
    repo_path: str,
    prefix: str,
    target: str = "main",
    all_worktrees: bool = False,
    auto_delete: bool = False,
    ui: UI | None = None,
) -> bool:
    """Executes the rebase-prefix command to batch rebase stack branches."""
    if ui is None:
        ui = UI()

    if not prefix:
        ui.print("Error: Missing <prefix>.")
        return False

    repo = pygit2.Repository(repo_path)

    start_branch = ""
    try:
        if not repo.head_is_detached and not repo.head_is_unborn:
            start_branch = repo.head.shorthand
    except pygit2.GitError:
        pass

    if not ui_update_target(repo_path, target, ui):
        restore_branch(repo_path, start_branch)
        return False

    ui.print(f"[dim]🔍  Scanning 'refs/heads/{prefix}*'...[/dim]")
    all_branches = _find_matching_branches(repo, prefix, target)

    if not all_branches:
        ui.print("  [yellow]No matching branches found.[/yellow]")
        restore_branch(repo_path, start_branch)
        return True

    return execute_batch_rebase(
        repo_path=repo_path,
        branches=all_branches,
        prefix=prefix,
        target=target,
        start_branch=start_branch,
        all_worktrees=all_worktrees,
        auto_delete=auto_delete,
        ui=ui,
    )
