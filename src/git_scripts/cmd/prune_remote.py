"""Core logic for the git-prune-remote-prefix command."""

import time

from rich.panel import Panel

from git_scripts.git.reads import get_repo, is_obsolete
from git_scripts.git.writes import GitExecutionError, run_cmd
from git_scripts.ui import UI


def _find_obsolete_remote_branches(
    repo, prefix: str, target: str, search_depth: int, ui
) -> list[str]:
    """Scans and analyzes remote branches to find obsolete ones."""
    ui.print(
        f"[dim]🔍  Scanning 'origin/{prefix}*' for obsolete branches...[/dim]"
    )

    start_time = time.time()
    to_delete = []

    with ui.spinner("Analyzing remote branch obsolescence"):
        for ref in repo.references:
            if ref.startswith(f"refs/remotes/origin/{prefix}"):
                if (
                    ref == "refs/remotes/origin/HEAD"
                    or ref == f"refs/remotes/origin/{target}"
                ):
                    continue

                branch_commit = repo.revparse_single(ref)
                if is_obsolete(
                    repo,
                    branch_commit.id,
                    f"refs/remotes/origin/{target}",
                    search_depth=search_depth,
                ):
                    # Strip refs/remotes/origin/
                    clean_name = ref[len("refs/remotes/origin/") :]
                    to_delete.append(clean_name)
    elapsed = time.time() - start_time
    ui.print(
        f"  [dim]⏱️  Remote obsolescence scan completed in {elapsed:.2f}s[/dim]"
    )
    return to_delete


def execute_prune_remote(
    repo_path: str,
    prefix: str,
    target: str = "main",
    dry_run: bool = False,
    search_depth: int = 100,
    ui=None,
) -> bool:
    """Prunes obsolete remote branches that match a prefix."""
    if ui is None:
        ui = UI()

    if not prefix:
        ui.print("❌  Error: Missing <prefix>.")
        return False

    if dry_run:
        ui.print("Running git-prune-remote-prefix in dry-run mode...")

    ui.print("[dim]🔄  Fetching origin...[/dim]")
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_path)
    except GitExecutionError:
        pass

    repo = get_repo(repo_path)

    try:
        repo.revparse_single(f"refs/remotes/origin/{target}")
    except KeyError:
        ui.print(f"❌  Error: Remote target 'origin/{target}' not found.")
        return False

    to_delete = _find_obsolete_remote_branches(
        repo, prefix, target, search_depth, ui
    )

    if not to_delete:
        ui.print("✅  No obsolete remote branches found.")
        return True

    branch_list = "\n".join(f"  - [cyan]{b}[/cyan]" for b in to_delete)
    ui.print(
        Panel(
            branch_list,
            title=(
                f"[bold yellow]Found {len(to_delete)} "
                "obsolete remote branches[/bold yellow]"
            ),
            border_style="yellow",
            expand=False,
        )
    )

    if dry_run:
        ui.print("\n📦  [Dry Run] No changes made.")
        return True

    if not ui.auto_yes:
        action = ui.ask_choice(
            f"❓  Delete the {len(to_delete)} obsolete remote branches?",
            choices=["Skip all", "Select which to delete", "Delete all"],
            default="Skip all",
        )

        if action == "Delete all":
            pass  # Keep to_delete as is
        elif action == "Select which to delete":
            to_delete = ui.ask_checkbox(
                "Select obsolete remote branches to delete:", choices=to_delete
            )
        else:
            to_delete = []

    if not to_delete:
        return True

    ui.print("\n🔥  Deleting from origin...")
    try:
        # Atomic delete
        run_cmd(
            ["git", "push", "origin", "--delete"] + to_delete, cwd=repo_path
        )
        ui.print("✅  Remote cleanup complete.")
        return True
    except GitExecutionError as e:
        ui.print(f"❌  Error during deletion: {e}")
        return False
