"""Core logic for the git-push-prefix command."""

import pygit2
from rich.panel import Panel

from git_scripts.git.writes import GitExecutionError, push_branches, run_cmd
from git_scripts.ui import UI


def _get_out_of_sync_branches(
    repo: pygit2.Repository, prefix: str
) -> tuple[list[str], int]:
    """Finds local branches matching prefix that differ from remote."""
    branches_to_push = []
    up_to_date_count = 0

    for ref in repo.references:
        if ref.startswith(f"refs/heads/{prefix}"):
            short_name = ref[len("refs/heads/") :]
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

    return branches_to_push, up_to_date_count


def execute_push_prefix(
    repo_path: str, prefix: str, push_opts: list[str] | None = None, ui=None
) -> bool:
    """Pushes out-of-sync local branches matching the prefix to the remote."""
    if ui is None:
        ui = UI()

    if push_opts is None:
        push_opts = []

    repo = pygit2.Repository(repo_path)

    ui.print("[cyan]🔄  Fetching origin...[/cyan]")
    # We could do a subprocess fetch here, or use pygit2.
    # We will just shell out for fetch as it handles auth natively.
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_path)
    except GitExecutionError:
        pass

    ui.print(f"[cyan]🔍  Scanning 'refs/heads/{prefix}*'...[/cyan]")

    branches_to_push, up_to_date_count = _get_out_of_sync_branches(
        repo, prefix
    )

    if not branches_to_push:
        if up_to_date_count == 0:
            ui.print("    No matching branches found.")
        else:
            ui.print(
                f"✅  All matched branches ({up_to_date_count}) "
                "are already up-to-date with origin."
            )
        return True

    branch_list = "\n".join(f"  - [cyan]{b}[/cyan]" for b in branches_to_push)
    ui.print(
        Panel(
            branch_list,
            title=(
                f"[bold cyan]Found {len(branches_to_push)} branches to "
                f"push[/bold cyan] [dim](Skipped {up_to_date_count} "
                "up-to-date)[/dim]"
            ),
            border_style="cyan",
            expand=False,
        )
    )

    if not ui.auto_yes:
        action = ui.ask_choice(
            f"❓  Push {len(branches_to_push)} branches to origin?",
            choices=["Push all", "Select which to push", "Skip all"],
            default="Push all",
        )
        match action:
            case "Skip all":
                ui.print("❌  Operation cancelled.")
                return True
            case "Select which to push":
                branches_to_push = ui.ask_checkbox(
                    "Select branches to push:", choices=branches_to_push
                )

    if not branches_to_push:
        ui.print("❌  Operation cancelled.")
        return True

    opts_str = " ".join(push_opts) or "(none)"
    ui.print(f"\n🚀  Pushing to origin (Options: {opts_str})...")
    if push_branches(branches_to_push, push_opts, repo_path=repo_path):
        ui.print("\n✅  Batch push complete.")
        return True
    else:
        ui.print("\n[red]❌  Push failed.[/red]")
        return False
