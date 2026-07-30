"""Git subprocess wrappers for state-mutating operations."""

import os
import shlex
import subprocess
from contextlib import contextmanager
from typing import Dict, Generator, List, Optional, Set, Tuple


class GitExecutionError(Exception):
    """Custom exception for git subprocess errors."""

    pass


def run_cmd(
    cmd: List[str], cwd: Optional[str] = None, check: bool = True
) -> str:
    """Executes a subprocess command and returns stripped stdout."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        raise GitExecutionError(
            f"Command failed: {cmd_str}\nError: {e.stderr.strip()}"
        ) from e


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


def _detach_worktrees(
    prefix: str = "", repo_path: str = "."
) -> Tuple[Dict[str, str], Set[str]]:
    """Detaches HEAD in all inactive worktrees to free branches.

    Git strictly locks branches that are checked out in any worktree,
    preventing them from being rebased or modified. This safely detaches
    their HEADs (storing their original state in detached_map) so that
    cross-worktree batch operations can succeed without git lock errors.
    """
    detached_map: Dict[str, str] = {}
    failed_branches: Set[str] = set()
    try:
        worktrees_out = run_cmd(
            ["git", "worktree", "list", "--porcelain"], cwd=repo_path
        )
    except GitExecutionError as e:
        print(f"DEBUG Error: {e}")
        return detached_map, failed_branches

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

            if prefix and not branch_name.startswith(prefix):
                continue

            # Skip current worktree
            if current_wt == toplevel:
                continue

            # Check if busy (merge/rebase in progress)
            try:
                git_dir = run_cmd(
                    ["git", "rev-parse", "--git-dir"], cwd=current_wt
                )

                if (
                    os.path.exists(
                        os.path.join(current_wt, git_dir, "MERGE_HEAD")
                    )
                    or os.path.exists(
                        os.path.join(current_wt, git_dir, "rebase-merge")
                    )
                    or os.path.exists(
                        os.path.join(current_wt, git_dir, "rebase-apply")
                    )
                ):
                    print(
                        f"⚠️  Warning: Worktree '{current_wt}' is busy. "
                        f"Skipping detach for '{branch_name}'."
                    )
                    failed_branches.add(branch_name)
                    continue
            except GitExecutionError:
                pass

            # Detach
            try:
                sha = run_cmd(["git", "rev-parse", branch_name], cwd=repo_path)
                print(
                    f"    Detaching '{branch_name}' in worktree "
                    f"'{current_wt}'..."
                )
                run_cmd(["git", "checkout", sha, "--detach"], cwd=current_wt)
                detached_map[current_wt] = branch_name
            except GitExecutionError as e:
                print(
                    f"⚠️  Warning: Failed to detach '{branch_name}' in "
                    f"{current_wt}:\n{e}"
                )
                failed_branches.add(branch_name)

    return detached_map, failed_branches


def _reattach_worktrees(
    detached_map: Dict[str, str], repo_path: str = "."
) -> None:
    """Re-checks out branches in their respective worktrees."""
    for wt, branch in detached_map.items():
        try:
            run_cmd(["git", "checkout", branch], cwd=wt)
        except GitExecutionError as e:
            print(
                f"⚠️  Warning: Could not re-attach '{branch}' in '{wt}'.\n{e}"
            )


@contextmanager
def manage_worktrees(
    prefix: str = "", active: bool = True, repo_path: str = "."
) -> Generator[Tuple[Dict[str, str], Set[str]], None, None]:
    """Temporarily detaches branches in other worktrees during execution.

    Yields empty context if active=False to simplify conditional usage.
    """
    detached_map = {}
    failed_branches = set()
    if active:
        detached_map, failed_branches = _detach_worktrees(prefix, repo_path)
    try:
        yield detached_map, failed_branches
    finally:
        if active:
            _reattach_worktrees(detached_map, repo_path)


def rebase_onto(
    onto_hash: str, old_base_hash: str, branch: str, repo_path: str = "."
) -> bool:
    """Executes git rebase --onto with --update-refs to port a stack."""
    try:
        run_cmd(
            [
                "git",
                "rebase",
                "--update-refs",
                "--rebase-merges",
                "--onto",
                onto_hash,
                old_base_hash,
                branch,
            ],
            cwd=repo_path,
        )
        return True
    except GitExecutionError as e:
        try:
            run_cmd(["git", "rebase", "--abort"], cwd=repo_path, check=False)
        except GitExecutionError:
            pass
        raise e


def rebase_standard(target: str, branch: str, repo_path: str = ".") -> bool:
    """Executes a standard git rebase onto the target branch."""
    try:
        run_cmd(
            [
                "git",
                "rebase",
                "--update-refs",
                "--rebase-merges",
                target,
                branch,
            ],
            cwd=repo_path,
        )
        return True
    except GitExecutionError as e:
        try:
            run_cmd(["git", "rebase", "--abort"], cwd=repo_path, check=False)
        except GitExecutionError:
            pass
        raise e


def push_branches(
    branches: List[str], options: List[str], repo_path: str = "."
) -> bool:
    """Pushes multiple branches to origin with optional git flags."""
    if not branches:
        return True
    cmd = ["git", "push", "origin"] + branches + options
    try:
        # We don't use run_cmd because we want to pipe to terminal
        # so auth prompts aren't swallowed
        subprocess.run(cmd, cwd=repo_path, check=True)
        return True
    except subprocess.CalledProcessError:
        return False
