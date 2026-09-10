"""Git worktree management utilities."""

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.models import WorktreeState


def is_in_another_worktree(repo_path: str, branch_name: str) -> bool:
    """Returns True if the branch is active in another git worktree."""
    try:
        current = run_cmd(["git", "branch", "--show-current"], cwd=repo_path)
        if current == branch_name:
            return False
        worktrees = run_cmd(
            ["git", "worktree", "list", "--porcelain"], cwd=repo_path
        )
        return f"branch refs/heads/{branch_name}" in worktrees.splitlines()
    except GitExecutionError:
        return False


def is_worktree_busy(current_wt: str) -> bool:
    """Checks if a worktree is currently in the middle of a merge or rebase."""
    try:
        git_dir = run_cmd(["git", "rev-parse", "--git-dir"], cwd=current_wt)
        return (
            os.path.exists(os.path.join(current_wt, git_dir, "MERGE_HEAD"))
            or os.path.exists(
                os.path.join(current_wt, git_dir, "rebase-merge")
            )
            or os.path.exists(
                os.path.join(current_wt, git_dir, "rebase-apply")
            )
        )
    except GitExecutionError:
        return False


@dataclass
class WorktreeLifecycleCallbacks:
    """Callbacks for worktree state transitions to decouple domain from UI."""

    on_busy: Callable[[str, str], None] = lambda wt, br: None
    on_detach: Callable[[str, str], None] = lambda wt, br: None
    on_detach_error: Callable[[str, str, str], None] = lambda wt, br, err: None
    on_reattach: Callable[[str, str], None] = lambda wt, br: None
    on_reattach_error: Callable[[str, str, str], None] = lambda wt, br, err: (
        None
    )
    on_debug: Callable[[str], None] = lambda err: None


def _process_worktree_branch(
    branch_name: str,
    current_wt: str,
    toplevel: str,
    prefix: str,
    target_branches: list[str] | None,
    repo_path: str,
    detached_map: dict[str, str],
    failed_branches: set[str],
    callbacks: WorktreeLifecycleCallbacks,
) -> None:
    if target_branches is not None and branch_name not in target_branches:
        return
    if prefix and not branch_name.startswith(prefix):
        return
    if current_wt == toplevel:
        return

    if is_worktree_busy(current_wt):
        callbacks.on_busy(current_wt, branch_name)
        failed_branches.add(branch_name)
        return

    try:
        sha = run_cmd(["git", "rev-parse", branch_name], cwd=repo_path)
        callbacks.on_detach(current_wt, branch_name)
        run_cmd(["git", "checkout", sha, "--detach"], cwd=current_wt)
        detached_map[current_wt] = branch_name
    except GitExecutionError as e:
        callbacks.on_detach_error(current_wt, branch_name, str(e))
        failed_branches.add(branch_name)


def _detach_worktrees(
    prefix: str = "",
    repo_path: str = ".",
    target_branches: list[str] | None = None,
    callbacks: WorktreeLifecycleCallbacks | None = None,
) -> WorktreeState:
    """Detaches HEAD in all inactive worktrees to free branches.

    Git strictly locks branches that are checked out in any worktree,
    preventing them from being rebased or modified. This safely detaches
    their HEADs (storing their original state in detached_map) so that
    cross-worktree batch operations can succeed without git lock errors.
    """
    if callbacks is None:
        callbacks = WorktreeLifecycleCallbacks()

    detached_map: dict[str, str] = {}
    failed_branches: set[str] = set()
    try:
        worktrees_out = run_cmd(
            ["git", "worktree", "list", "--porcelain"], cwd=repo_path
        )
    except GitExecutionError as e:
        callbacks.on_debug(str(e))
        return WorktreeState(
            detached_map=detached_map, failed_branches=failed_branches
        )

    try:
        toplevel = run_cmd(
            ["git", "rev-parse", "--show-toplevel"], cwd=repo_path
        )
    except GitExecutionError:
        toplevel = ""

    current_wt = ""
    for line in worktrees_out.splitlines():
        if line.startswith("worktree "):
            current_wt = line[len("worktree ") :]
        elif line.startswith("branch refs/heads/"):
            branch_name = line[len("branch refs/heads/") :]
            _process_worktree_branch(
                branch_name=branch_name,
                current_wt=current_wt,
                toplevel=toplevel,
                prefix=prefix,
                target_branches=target_branches,
                repo_path=repo_path,
                detached_map=detached_map,
                failed_branches=failed_branches,
                callbacks=callbacks,
            )

    return WorktreeState(
        detached_map=detached_map, failed_branches=failed_branches
    )


def _reattach_worktrees(
    detached_map: dict[str, str],
    repo_path: str = ".",
    callbacks: WorktreeLifecycleCallbacks | None = None,
) -> None:
    """Re-checks out branches in their respective worktrees."""
    if callbacks is None:
        callbacks = WorktreeLifecycleCallbacks()

    for wt, branch in detached_map.items():
        try:
            callbacks.on_reattach(wt, branch)
            run_cmd(["git", "checkout", branch], cwd=wt)
        except GitExecutionError as e:
            callbacks.on_reattach_error(wt, branch, str(e))


@contextmanager
def manage_worktrees(
    prefix: str = "",
    active: bool = True,
    repo_path: str = ".",
    target_branches: list[str] | None = None,
    callbacks: WorktreeLifecycleCallbacks | None = None,
) -> Generator[WorktreeState, None, None]:
    """Temporarily detaches branches in other worktrees during execution.

    Yields empty context if active=False to simplify conditional usage.
    """
    state = WorktreeState(detached_map={}, failed_branches=set())
    if active:
        state = _detach_worktrees(
            prefix, repo_path, target_branches, callbacks
        )
    try:
        yield state
    finally:
        if active:
            _reattach_worktrees(state.detached_map, repo_path, callbacks)
