"""Core logic for pushing branches in the checked-out linear stack."""

import pygit2

from git_scripts.cmd.shared import (
    get_local_branch_pool,
    order_stack_branches,
    partition_out_of_sync_branches,
    resolve_branches_to_push,
    resolve_linear_stack,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.remote import push_branches
from git_scripts.ui import UI


def execute_push_stack(
    repo_path: str,
    target: str = "main",
    push_opts: list[str] | None = None,
    ui: UI | None = None,
) -> bool:
    """Pushes out-of-sync local branches in the current stack to the remote."""
    if ui is None:
        ui = UI()

    if push_opts is None:
        push_opts = []

    repo = pygit2.Repository(repo_path)

    if repo.head_is_detached:
        ui.print("[red]❌  Cannot push stack from detached HEAD.[/red]")
        return False

    current_branch = repo.head.shorthand

    ui.print("[cyan]🔄  Fetching origin...[/cyan]")
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_path)
    except GitExecutionError:
        pass

    ui.print(f"[cyan]🔍  Analyzing stack for '{current_branch}'...[/cyan]")

    pool = get_local_branch_pool(repo, target)
    stack = resolve_linear_stack(
        repo, current_branch, target, pool, ui, action_verb="push"
    )
    if stack is None:
        return False

    ordered_stack = order_stack_branches(repo, stack, target)
    if not ordered_stack:
        ui.print(
            f"    No branches found in stack between '{current_branch}' "
            f"and target '{target}'."
        )
        return True

    branches_to_push, up_to_date_count = partition_out_of_sync_branches(
        repo, ordered_stack
    )

    is_dry_run = any(opt in ("-n", "--dry-run") for opt in push_opts)
    branches_to_push = resolve_branches_to_push(
        branches=branches_to_push,
        ui=ui,
        prompt_title=(
            f"Push {ui.pluralize(len(branches_to_push), 'branch')} "
            "in stack to origin?"
        ),
        dry_run=is_dry_run,
    )

    if not branches_to_push:
        if up_to_date_count > 0:
            ui.print(
                f"✅  {ui.pluralize(up_to_date_count, 'branch')} already "
                "up-to-date. No branches to push."
            )
        return True

    return push_branches(
        branches=branches_to_push,
        options=push_opts,
        repo_path=repo_path,
    )
