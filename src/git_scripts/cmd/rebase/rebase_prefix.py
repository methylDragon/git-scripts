"""Core logic for the git prefix rebase (git-rebase-prefix) command."""

import time

import pygit2

from git_scripts.cmd.rebase.rebase_orchestrator import (
    print_batch_summary,
    prompt_and_delete_merged,
    prompt_and_push_updated_branches,
    rebase_loop,
)
from git_scripts.cmd.shared import ui_update_target
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.topology import TopologyAnalyzer
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


def _restore_branch(repo_path: str, branch: str) -> None:
    if branch:
        try:
            run_cmd(["git", "checkout", branch], cwd=repo_path)
        except GitExecutionError:
            pass


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
        _restore_branch(repo_path, start_branch)
        return False

    ui.print(f"[dim]🔍  Scanning 'refs/heads/{prefix}*'...[/dim]")
    all_branches = _find_matching_branches(repo, prefix, target)

    if not all_branches:
        ui.print("  [yellow]No matching branches found.[/yellow]")
        return True

    analyzer = TopologyAnalyzer(repo_path, all_branches)
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

    branch_pool = set(all_branches)
    batch_result, completed = rebase_loop(
        analyzer,
        repo_path,
        prefix,
        target,
        all_worktrees,
        ui,
        branch_pool,
    )
    if not completed:
        return False

    print_batch_summary(ui, batch_result)
    prompt_and_delete_merged(batch_result, auto_delete, ui, repo_path)

    _restore_branch(repo_path, start_branch)

    prompt_and_push_updated_branches(
        batch_result.branches_to_keep, repo_path, ui
    )

    return len(batch_result.failed_log) == 0
