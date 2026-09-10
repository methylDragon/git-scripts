"""Git remote operations (fetch, pull, push)."""

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.worktrees import is_in_another_worktree
from git_scripts.models import UpdateTargetResult


def update_target(repo_path: str, target: str) -> UpdateTargetResult:
    """Fetches and rebases the target branch from its remote upstream.

    Returns:
        UpdateTargetResult indicating the result state.

    Raises:
        GitExecutionError: if target does not exist or fails to pull.
    """
    try:
        # Check if target exists
        run_cmd(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target}"],
            cwd=repo_path,
        )
    except GitExecutionError as err:
        raise GitExecutionError(
            f"Target branch '{target}' does not exist locally."
        ) from err

    current = run_cmd(["git", "branch", "--show-current"], cwd=repo_path)
    if current != target:
        if is_in_another_worktree(repo_path, target):
            try:
                run_cmd(
                    ["git", "fetch", "origin", target],
                    cwd=repo_path,
                    check=False,
                )
            except GitExecutionError:
                pass
            return UpdateTargetResult.FETCHED_ONLY

        try:
            run_cmd(["git", "checkout", target], cwd=repo_path)
        except GitExecutionError as err:
            raise GitExecutionError(f"Could not checkout '{target}'.") from err

    # Check upstream
    upstream = run_cmd(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        ],
        cwd=repo_path,
        check=False,
    )

    if upstream:
        try:
            run_cmd(["git", "pull", "--rebase"], cwd=repo_path)
        except GitExecutionError as e:
            raise GitExecutionError(
                f"Could not pull updates. Aborting.\n{e}"
            ) from e
        return UpdateTargetResult.SUCCESS
    else:
        return UpdateTargetResult.LOCAL_ONLY


def push_branches(
    branches: list[str], options: list[str], repo_path: str = "."
) -> bool:
    """Pushes multiple branches to origin with optional git flags."""
    if not branches:
        return True
    cmd = ["git", "push", "origin"] + branches + options
    try:
        run_cmd(cmd, cwd=repo_path, capture_output=False)
        return True
    except GitExecutionError:
        return False
