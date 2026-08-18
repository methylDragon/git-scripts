"""Git subprocess wrappers for state-mutating operations."""

import os
import shlex
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager

from rich.panel import Panel

from git_scripts.models import WorktreeState
from git_scripts.ui import UI


class GitExecutionError(Exception):
    """Custom exception for git subprocess errors."""

    pass


def run_cmd(
    cmd: list[str],
    cwd: str | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> str:
    """Executes a subprocess command and returns stripped stdout."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            capture_output=capture_output,
            text=True,
        )
        return result.stdout.strip() if result.stdout else ""
    except subprocess.CalledProcessError as e:
        cmd_str = shlex.join(cmd)
        err_out = e.stderr.strip() if getattr(e, "stderr", None) else str(e)
        raise GitExecutionError(
            f"Command failed: {cmd_str}\nError: {err_out}"
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


def _is_worktree_busy(current_wt: str) -> bool:
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


def _detach_worktrees(prefix: str = "", repo_path: str = ".") -> WorktreeState:
    """Detaches HEAD in all inactive worktrees to free branches.

    Git strictly locks branches that are checked out in any worktree,
    preventing them from being rebased or modified. This safely detaches
    their HEADs (storing their original state in detached_map) so that
    cross-worktree batch operations can succeed without git lock errors.
    """
    detached_map: dict[str, str] = {}
    failed_branches: set[str] = set()
    try:
        worktrees_out = run_cmd(
            ["git", "worktree", "list", "--porcelain"], cwd=repo_path
        )
    except GitExecutionError as e:
        print(f"DEBUG Error: {e}")
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

            if prefix and not branch_name.startswith(prefix):
                continue

            # Skip current worktree
            if current_wt == toplevel:
                continue

            # Check if busy (merge/rebase in progress)
            if _is_worktree_busy(current_wt):
                print(
                    f"⚠️  Warning: Worktree '{current_wt}' is busy. "
                    f"Skipping detach for '{branch_name}'."
                )
                failed_branches.add(branch_name)
                continue

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

    return WorktreeState(
        detached_map=detached_map, failed_branches=failed_branches
    )


def _reattach_worktrees(
    detached_map: dict[str, str], repo_path: str = "."
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
) -> Generator[WorktreeState, None, None]:
    """Temporarily detaches branches in other worktrees during execution.

    Yields empty context if active=False to simplify conditional usage.
    """
    state = WorktreeState(detached_map={}, failed_branches=set())
    if active:
        state = _detach_worktrees(prefix, repo_path)
    try:
        yield state
    finally:
        if active:
            _reattach_worktrees(state.detached_map, repo_path)


def _handle_rebase_conflict(e: GitExecutionError, repo_path: str, ui) -> bool:
    """Handles git rebase conflicts by prompting the user for resolution."""
    if not ui:
        try:
            run_cmd(["git", "rebase", "--abort"], cwd=repo_path, check=False)
        except GitExecutionError:
            pass
        raise e

    err_msg = str(e)
    if "Error:" in err_msg:
        err_msg = err_msg.split("Error:", 1)[1].strip()
    ui.print(f"    [red]❌  Conflict or error.\n{err_msg}[/red]")

    while True:
        ans = ui.ask_choice(
            "How would you like to handle this?",
            choices=[
                "Abort rebase and rollback",
                "Resolve manually, then continue",
                "Abort script without rollback",
            ],
            default="Abort rebase and rollback",
        )

        match ans:
            case "Abort script without rollback":
                ui.print(
                    "    [yellow]Leaving repository in current state "
                    "(rebase in progress).[/yellow]"
                )
                sys.exit(1)
            case "Resolve manually, then continue":
                ui.print(
                    "    [yellow]Please resolve the conflicts in another "
                    "terminal. (DO NOT run `git rebase --continue`)[/yellow]"
                )
                ui.pause(
                    "    [cyan]When the conflicts are completely "
                    "resolved, press \\[[bold]ENTER[/bold]]...[/cyan]"
                )

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
                    ui.print("    ✅  Rebase finished. Continuing script...")
                    return True
                except GitExecutionError as e:
                    err_msg = str(e)
                    if "Error:" in err_msg:
                        err_msg = err_msg.split("Error:", 1)[1].strip()
                    ui.print(
                        f"    [red]⚠️  Rebase could not continue.\n"
                        f"{err_msg}[/red]"
                    )
                    continue
            case _:
                try:
                    run_cmd(
                        ["git", "rebase", "--abort"],
                        cwd=repo_path,
                        check=False,
                    )
                except GitExecutionError:
                    pass
                raise e


def rebase_onto(
    onto_hash: str,
    old_base_hash: str,
    branch: str,
    repo_path: str = ".",
    ui=None,
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
        return _handle_rebase_conflict(e, repo_path, ui)


def rebase_standard(
    target: str,
    branch: str,
    repo_path: str = ".",
    ui=None,
) -> bool:
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
        return _handle_rebase_conflict(e, repo_path, ui)


def push_branches(
    branches: list[str], options: list[str], repo_path: str = "."
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


def prompt_and_push_branches(
    branches: list[str],
    ui: UI,
    push_opts: list[str] | None = None,
    repo_path: str = ".",
    skipped_count: int = 0,
    prompt_title: str | None = None,
    panel_title: str | None = None,
) -> bool:
    """Displays branches, prompts for selection, and pushes."""
    if push_opts is None:
        push_opts = []

    if not branches:
        if skipped_count == 0:
            ui.print("    No matching branches found.")
        else:
            ui.print(
                f"✅  All branches ({skipped_count}) "
                "are already up-to-date with origin."
            )
        return True

    branch_list = "\n".join(f"  - [cyan]{b}[/cyan]" for b in branches)
    skipped_str = (
        f" [dim](Skipped {skipped_count} up-to-date)[/dim]"
        if skipped_count > 0
        else ""
    )

    if panel_title is None:
        panel_title = (
            f"[bold cyan]Found {len(branches)} branches to push[/bold cyan]"
        )

    ui.print(
        Panel(
            branch_list,
            title=f"{panel_title}{skipped_str}",
            border_style="cyan",
            expand=False,
        )
    )

    branches_to_push = list(branches)
    if not ui.auto_yes:
        if prompt_title is None:
            prompt_title = f"Push {len(branches)} branches to origin?"
        action = ui.ask_choice(
            f"❓  {prompt_title}",
            choices=["Push all", "Select which to push", "Skip all"],
            default="Push all",
        )
        match action:
            case "Skip all" | None:
                ui.print("⏭️  Push skipped.")
                return True
            case "Select which to push":
                branches_to_push = ui.ask_checkbox(
                    "Select branches to push:", choices=branches_to_push
                )

    if not branches_to_push:
        ui.print("⏭️  Push skipped.")
        return True

    opts_str = " ".join(push_opts) or "(none)"
    ui.print(f"\n🚀  Pushing to origin (Options: {opts_str})...")
    if push_branches(branches_to_push, push_opts, repo_path=repo_path):
        ui.print("\n✅  Batch push complete.")
        return True
    else:
        ui.print("\n[red]❌  Push failed.[/red]")
        return False
