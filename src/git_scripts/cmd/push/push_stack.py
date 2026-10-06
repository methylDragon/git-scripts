"""Core logic for the git stack push (git-push-stack) command."""

import pygit2

from git_scripts.cmd.shared import (
    get_local_branch_pool,
    order_stack_branches,
    resolve_branches_to_push,
    resolve_linear_stack,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.remote import push_branches
from git_scripts.ui import UI


def _get_out_of_sync_branches_in_stack(
    repo: pygit2.Repository, stack_branches: list[str]
) -> tuple[list[str], int]:
    """Finds branches in the stack that differ from remote."""
    branches_to_push = []
    up_to_date_count = 0

    for short_name in stack_branches:
        ref = f"refs/heads/{short_name}"
        try:
            local_commit = repo.revparse_single(ref)
            try:
                remote_commit = repo.revparse_single(
                    f"refs/remotes/origin/{short_name}"
                )
                if local_commit.id != remote_commit.id:
                    branches_to_push.append(short_name)
                else:
                    up_to_date_count += 1
            except KeyError:
                branches_to_push.append(short_name)
        except KeyError:
            continue

    return branches_to_push, up_to_date_count


def _get_linear_stack(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    ui: UI,
) -> set[str] | None:
    """Discovers the linear stack containing current_branch within pool."""
    return resolve_linear_stack(
        repo, current_branch, target, pool, ui, action_verb="push"
    )


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
    stack = _get_linear_stack(repo, current_branch, target, pool, ui)
    if stack is None:
        return False

    ordered_stack = order_stack_branches(repo, stack, target)
    if not ordered_stack:
        ui.print(
            f"    No branches found in stack between '{current_branch}' "
            f"and target '{target}'."
        )
        return True

    branches_to_push, up_to_date_count = _get_out_of_sync_branches_in_stack(
        repo, ordered_stack
    )

    branches_to_push = resolve_branches_to_push(
        branches=branches_to_push,
        ui=ui,
        prompt_title=(
            f"Push {ui.pluralize(len(branches_to_push), 'branch')} "
            "in stack to origin?"
        ),
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
