"""Git subprocess wrappers for state-mutating operations."""

import shlex
import subprocess
import sys

from rich.panel import Panel

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


def update_target(repo_path: str, target: str, ui) -> bool:
    """Fetches and rebases the target branch from its remote upstream."""
    from git_scripts.git.worktrees import is_in_another_worktree

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


def _handle_rebase_conflict(
    e: GitExecutionError, repo_path: str, ui, branch: str = ""
) -> bool:
    """Handles git rebase conflicts by prompting the user for resolution."""
    from git_scripts.git.worktrees import is_worktree_busy

    if not ui:
        try:
            run_cmd(["git", "rebase", "--abort"], cwd=repo_path, check=False)
        except GitExecutionError:
            pass
        raise e

    err_msg = str(e)
    if "Error:" in err_msg:
        err_msg = err_msg.split("Error:", 1)[1].strip()

    branch_msg = f" on branch '[bold]{branch}[/bold]'" if branch else ""
    ui.print(f"    [red]❌  Conflict or error{branch_msg}.\n{err_msg}[/red]")

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
                    if not is_worktree_busy(repo_path):
                        ui.print(
                            "    [yellow]⚠️  No active rebase detected.\n"
                            "    It seems you may have already run "
                            "`git rebase --continue` or `--abort` "
                            "manually.[/yellow]"
                        )
                        ans2 = ui.ask_choice(
                            "Did you successfully complete the rebase?",
                            choices=["Yes", "No (Treat as aborted)"],
                            default="Yes",
                        )
                        if ans2 == "Yes":
                            ui.print(
                                "    ✅  Rebase assumed finished. "
                                "Continuing script..."
                            )
                            return True
                        else:
                            ui.print("    ❌  Rebase marked as aborted.")
                            try:
                                run_cmd(
                                    ["git", "rebase", "--abort"],
                                    cwd=repo_path,
                                    check=False,
                                )
                            except GitExecutionError:
                                pass
                            raise e

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
        return _handle_rebase_conflict(e, repo_path, ui, branch=branch)


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
        return _handle_rebase_conflict(e, repo_path, ui, branch=branch)


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
