"""Core logic for the git stack rebase (git-rebase-stack) command."""

import pygit2

from git_scripts.cmd.rebase.rebase_orchestrator import execute_batch_rebase
from git_scripts.cmd.shared import (
    get_local_branch_pool,
    order_stack_branches,
    resolve_linear_stack,
    restore_branch,
    ui_update_target,
)
from git_scripts.ui import UI


def _get_linear_stack(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    ui: UI,
) -> set[str] | None:
    """Finds the full linear stack containing current_branch within pool."""
    return resolve_linear_stack(
        repo, current_branch, target, pool, ui, action_verb="rebase"
    )


def execute_rebase_stack(
    repo_path: str = ".",
    target: str = "main",
    all_worktrees: bool = False,
    auto_delete: bool = False,
    ui: UI | None = None,
) -> bool:
    """Executes the rebase-stack command to rebase the current linear stack."""
    if ui is None:
        ui = UI()

    repo = pygit2.Repository(repo_path)

    if repo.head_is_detached:
        ui.print("[red]❌  Cannot rebase stack from detached HEAD.[/red]")
        return False

    current_branch = repo.head.shorthand

    if current_branch == target:
        ui.print(
            f"[yellow]Current branch is target branch '{target}'. "
            "Nothing to rebase.[/yellow]"
        )
        return True

    ui.print(f"[dim]🔍  Analyzing stack for '{current_branch}'...[/dim]")

    pool = get_local_branch_pool(repo, target)
    stack = _get_linear_stack(repo, current_branch, target, pool, ui)
    if stack is None:
        return False

    ordered_stack = order_stack_branches(repo, stack, target)
    if not ordered_stack:
        ui.print(
            f"  [yellow]No branches found in stack between '{current_branch}' "
            f"and target '{target}'.[/yellow]"
        )
        return True

    if not ui_update_target(repo_path, target, ui):
        restore_branch(repo_path, current_branch)
        return False

    return execute_batch_rebase(
        repo_path=repo_path,
        branches=ordered_stack,
        prefix="",
        target=target,
        start_branch=current_branch,
        all_worktrees=all_worktrees,
        auto_delete=auto_delete,
        ui=ui,
    )
