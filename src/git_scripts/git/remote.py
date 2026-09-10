"""Git remote operations (fetch, pull, push)."""

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.worktrees import is_in_another_worktree


def update_target(repo_path: str, target: str, ui) -> bool:
    """Fetches and rebases the target branch from its remote upstream."""
    try:
        # Check if target exists
        run_cmd(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target}"],
            cwd=repo_path,
        )
    except GitExecutionError:
        ui.print(
            f"❌  Error: Target branch '{target}' does not exist locally."
        )
        return False

    try:
        current = run_cmd(["git", "branch", "--show-current"], cwd=repo_path)
        if current != target:
            if is_in_another_worktree(repo_path, target):
                ui.print(
                    f"⚠️  Warning: Target branch '{target}' is in another "
                    "worktree. Fetching its remote tracking branch instead."
                )
                try:
                    run_cmd(
                        ["git", "fetch", "origin", target],
                        cwd=repo_path,
                        check=False,
                    )
                except GitExecutionError:
                    pass
                return True

            try:
                run_cmd(["git", "checkout", target], cwd=repo_path)
            except GitExecutionError:
                ui.print(f"❌  Error: Could not checkout '{target}'.")
                return False

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
            ui.print(f"🔄  Pulling updates from {upstream}...")
            try:
                run_cmd(["git", "pull", "--rebase"], cwd=repo_path)
            except GitExecutionError:
                ui.print("❌  Error: Could not pull updates. Aborting.")
                return False
        else:
            ui.print(
                f"⚠️  '{target}' is local-only (no upstream). Using "
                "current state."
            )
        return True
    except Exception as e:
        ui.print(f"❌  Error updating target: {e}")
        return False


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
