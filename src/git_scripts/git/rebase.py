"""Git rebase operations."""

import sys

from rich.panel import Panel

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.remote import push_branches
from git_scripts.git.worktrees import is_worktree_busy
from git_scripts.ui import UI


def _handle_rebase_conflict(
    e: GitExecutionError, repo_path: str, ui: UI | None, branch: str = ""
) -> bool:
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
                except GitExecutionError as e_inner:
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
                            raise e_inner

                    err_msg = str(e_inner)
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


def rebase_stack_onto(
    new_parent_commit: str,
    old_parent_commit: str,
    tip_branch: str,
    repo_path: str = ".",
    ui: UI | None = None,
) -> bool:
    """Rebases a stack by explicitly replacing its base commit.

    Uses `git rebase --onto <newbase> <oldbase>` along with `--update-refs`
    and `--rebase-merges` to move the branch and all its downstream
    dependencies to `new_parent_commit`.

    Use this instead of `rebase_stack` when the target branch has been
    rewritten (e.g., via a squash merge). A standard rebase would replay
    the obsolete commits, causing conflicts. This method safely transplants
    the stack starting exactly after `old_parent_commit`.

    Args:
        new_parent_commit: The new base commit.
        old_parent_commit: The old base commit to exclude.
        tip_branch: The tip branch of the stack being moved.
        repo_path: Path to the git repository.
        ui: Optional UI instance for prompting on conflict.

    Returns:
        True if the rebase was successful, False if aborted due to conflict.
    """
    try:
        run_cmd(
            [
                "git",
                "rebase",
                "--update-refs",
                "--rebase-merges",
                "--onto",
                new_parent_commit,
                old_parent_commit,
                tip_branch,
            ],
            cwd=repo_path,
        )
        return True
    except GitExecutionError as e:
        return _handle_rebase_conflict(e, repo_path, ui, branch=tip_branch)


def rebase_stack(
    new_base_branch: str,
    tip_branch: str,
    repo_path: str = ".",
    ui: UI | None = None,
) -> bool:
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
        ui: Optional UI instance for prompting on conflict.

    Returns:
        True if the rebase was successful, False if aborted due to conflict.
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
        return True
    except GitExecutionError as e:
        return _handle_rebase_conflict(e, repo_path, ui, branch=tip_branch)


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
