"""Core logic for the git stack rebase (git-rebase-stack) command."""

import time

import pygit2

from git_scripts.cmd.rebase.rebase_orchestrator import (
    print_batch_summary,
    prompt_and_delete_merged,
    prompt_and_push_updated_branches,
    rebase_loop,
)
from git_scripts.cmd.shared import (
    get_local_branch_pool,
    order_stack_branches,
    resolve_linear_stack,
    ui_update_target,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.topology import TopologyAnalyzer
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
        try:
            run_cmd(["git", "checkout", current_branch], cwd=repo_path)
        except GitExecutionError:
            pass
        return False

    analyzer = TopologyAnalyzer(repo_path, ordered_stack)
    ui.print(f"  [bold]Found {len(analyzer.tips)} stack tips.[/bold]")

    start_time = time.time()
    analyzer.analyze_obsolescence(
        target,
        progress_callback=lambda msg: ui.print(f"  [dim]⏳ {msg}[/dim]"),
    )
    elapsed = time.time() - start_time
    ui.print(f"  [dim]⏱️  Topology analysis completed in {elapsed:.2f}s[/dim]")

    if all_worktrees:
        ui.print(
            "[dim]🔄  Detaching worktrees for cross-worktree rebase...[/dim]"
        )

    branch_pool = set(ordered_stack)
    batch_result, completed = rebase_loop(
        analyzer,
        repo_path,
        "",
        target,
        all_worktrees,
        ui,
        branch_pool,
    )
    if not completed:
        return False

    print_batch_summary(ui, batch_result)

    prompt_and_delete_merged(batch_result, auto_delete, ui, repo_path)

    try:
        run_cmd(["git", "checkout", current_branch], cwd=repo_path)
    except GitExecutionError:
        pass

    prompt_and_push_updated_branches(
        batch_result.branches_to_keep, repo_path, ui
    )

    return len(batch_result.failed_log) == 0
