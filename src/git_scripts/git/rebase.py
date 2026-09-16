"""Git rebase operations."""

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.models import RebaseStatus


def _parse_rebase_error(
    e: GitExecutionError,
) -> tuple[RebaseStatus, str | None]:
    """Parses a GitExecutionError to determine if it's a conflict or fatal."""
    err_msg = str(e).lower()
    if (
        "conflict" in err_msg
        or "could not apply" in err_msg
        or "patch failed" in err_msg
    ):
        return RebaseStatus.CONFLICT, str(e)
    return RebaseStatus.ERROR, str(e)


def rebase_continue(repo_path: str = ".") -> tuple[RebaseStatus, str | None]:
    """Continues an in-progress rebase."""
    try:
        run_cmd(
            [
                "git",
                "-c",
                "core.editor=true",
                "rebase",
                "--continue",
            ],
            cwd=repo_path,
            capture_output=False,
        )
        return RebaseStatus.SUCCESS, None
    except GitExecutionError as e:
        return _parse_rebase_error(e)


def rebase_abort(repo_path: str = ".") -> None:
    """Aborts an in-progress rebase."""
    try:
        run_cmd(
            ["git", "rebase", "--abort"],
            cwd=repo_path,
            check=False,
        )
    except GitExecutionError:
        pass


def rebase_stack_onto(
    new_base_commit_hash: str,
    old_base_commit_hash: str,
    tip_branch: str,
    repo_path: str = ".",
) -> tuple[RebaseStatus, str | None]:
    """Rebases a stack by explicitly replacing its base commit.

    Uses `git rebase --onto <newbase> <oldbase>` along with `--update-refs`
    and `--rebase-merges` to move the branch and all its downstream
    dependencies to `new_base_commit_hash`.

    Use this instead of `rebase_stack` when the target branch has been
    rewritten (e.g., via a squash merge). A standard rebase would replay
    the obsolete commits, causing conflicts. This method safely transplants
    the stack starting exactly after `old_base_commit_hash`.

    Args:
        new_base_commit_hash: The new base commit hash.
        old_base_commit_hash: The old base commit hash to exclude.
        tip_branch: The tip branch of the stack being moved.
        repo_path: Path to the git repository.

    Returns:
        RebaseStatus indicating success, conflict, or error.
    """
    try:
        run_cmd(
            [
                "git",
                "rebase",
                "--update-refs",
                "--rebase-merges",
                "--onto",
                new_base_commit_hash,
                old_base_commit_hash,
                tip_branch,
            ],
            cwd=repo_path,
        )
        return RebaseStatus.SUCCESS, None
    except GitExecutionError as e:
        return _parse_rebase_error(e)


def rebase_stack(
    new_base_branch: str,
    tip_branch: str,
    repo_path: str = ".",
) -> tuple[RebaseStatus, str | None]:
    """Rebases a stack up to a target branch using its common ancestor.

    Uses `git rebase --update-refs --rebase-merges` to update the given branch
    and its downstream stack branches to the latest target commit.

    Use this when catching up a stack to the latest `main` commit, provided
    the stack's base commits have not been rewritten upstream. If the base
    commits were squashed or rewritten, use `rebase_stack_onto` instead.

    Args:
        new_base_branch: The upstream branch to rebase onto (e.g., 'main').
        tip_branch: The tip branch of the stack being caught up.
        repo_path: Path to the git repository.

    Returns:
        RebaseStatus indicating success, conflict, or error.
    """
    try:
        run_cmd(
            [
                "git",
                "rebase",
                "--update-refs",
                "--rebase-merges",
                new_base_branch,
                tip_branch,
            ],
            cwd=repo_path,
        )
        return RebaseStatus.SUCCESS, None
    except GitExecutionError as e:
        return _parse_rebase_error(e)
