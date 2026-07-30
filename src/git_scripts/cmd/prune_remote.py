"""Core logic for the git-prune-remote-prefix command."""

import time
from subprocess import CalledProcessError
from subprocess import run as subprocess_run

import pygit2
from rich.panel import Panel

from git_scripts.git.parallel import analyze_branches_in_parallel
from git_scripts.git.reads import get_repo, is_obsolete
from git_scripts.git.writes import GitExecutionError, run_cmd
from git_scripts.models import RemotePruneResult
from git_scripts.ui import UI


def _find_obsolete_remote_branches(
    repo_path: str,
    repo,
    prefix: str,
    target: str,
    also_prune_no_local: bool,
    ui,
) -> RemotePruneResult:
    """Scans and analyzes remote branches to find obsolete ones.

    Returns:
        A RemotePruneResult containing obsolete and unmerged branches.
    """
    ui.print(
        f"[dim]🔍  Scanning 'origin/{prefix}*' for obsolete branches...[/dim]"
    )

    start_time = time.time()

    local_branches = set(repo.branches.local)
    refs_to_check = []
    orphaned_remotes = []

    for ref in repo.references:
        if ref.startswith(f"refs/remotes/origin/{prefix}"):
            if ref in (
                "refs/remotes/origin/HEAD",
                f"refs/remotes/origin/{target}",
            ):
                continue

            short_name = ref[len("refs/remotes/origin/") :]
            if also_prune_no_local and short_name not in local_branches:
                orphaned_remotes.append(ref)

            refs_to_check.append(ref)

    def _check_obs(ref_name: str) -> bool:
        # thread safety just in case
        local_repo = pygit2.Repository(repo_path)
        commit_id = local_repo.revparse_single(ref_name).id
        return is_obsolete(
            local_repo,
            commit_id,
            f"refs/remotes/origin/{target}",
        )

    results = analyze_branches_in_parallel(
        repo_path=repo_path,
        branches=refs_to_check,
        target_ref=f"refs/remotes/origin/{target}",
        analyze_fn=_check_obs,
        description="Analyzing obsolescence",
        ui=ui,
    )

    obsolete_branches = []
    unmerged_no_local_branches = []

    for ref, obsolete in results.items():
        short_name = ref[len("refs/remotes/origin/") :]
        if obsolete:
            obsolete_branches.append(short_name)
        elif ref in orphaned_remotes:
            unmerged_no_local_branches.append(short_name)

    elapsed = time.time() - start_time
    ui.print(
        f"  [dim]⏱️  Remote obsolescence scan completed in {elapsed:.2f}s[/dim]"
    )
    return RemotePruneResult(
        obsolete_branches=obsolete_branches,
        unmerged_no_local_branches=unmerged_no_local_branches,
    )


def execute_prune_remote(
    repo_path: str,
    prefix: str,
    target: str = "main",
    dry_run: bool = False,
    also_prune_no_local: bool = False,
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

    prune_result = _find_obsolete_remote_branches(
        repo_path, repo, prefix, target, also_prune_no_local, ui
    )

    obsolete_branches = prune_result.obsolete_branches
    unmerged_no_local = prune_result.unmerged_no_local_branches

    if not obsolete_branches and not unmerged_no_local:
        ui.print("✅  No remote branches found for pruning.")
        return True

    if obsolete_branches:
        branch_list = "\n".join(
            f"  - [cyan]{b}[/cyan]" for b in obsolete_branches
        )
        ui.print(
            Panel(
                branch_list,
                title=(
                    f"[bold yellow]Found {len(obsolete_branches)} "
                    "obsolete remote branches[/bold yellow]"
                ),
                border_style="yellow",
                expand=False,
            )
        )

    if unmerged_no_local:
        branch_list = "\n".join(
            f"  - [red]{b}[/red]" for b in unmerged_no_local
        )
        ui.print(
            Panel(
                branch_list,
                title=(
                    f"[bold red]Found {len(unmerged_no_local)} "
                    "unmerged branches lacking local counterparts[/bold red]"
                ),
                border_style="red",
                expand=False,
            )
        )

    if dry_run:
        ui.print("\n📦  [Dry Run] No changes made.")
        return True

    return _prompt_and_delete_branches(
        obsolete_branches, unmerged_no_local, ui, repo_path
    )


def _prompt_and_delete_branches(
    obsolete_branches: list[str],
    unmerged_no_local: list[str],
    ui: UI,
    repo_path: str,
) -> bool:
    to_delete = []

    if obsolete_branches:
        if ui.auto_yes:
            to_delete.extend(obsolete_branches)
        else:
            action = ui.ask_choice(
                f"❓  Delete {len(obsolete_branches)} obsolete "
                "remote branches?",
                choices=["Skip all", "Select which to delete", "Delete all"],
                default="Delete all",
            )
            match action:
                case "Delete all":
                    to_delete.extend(obsolete_branches)
                case "Select which to delete":
                    to_delete.extend(
                        ui.ask_checkbox(
                            "Select obsolete remote branches to delete:",
                            choices=obsolete_branches,
                        )
                    )

    if unmerged_no_local:
        if ui.auto_yes:
            to_delete.extend(unmerged_no_local)
        else:
            action = ui.ask_choice(
                f"⚠️  Delete {len(unmerged_no_local)} unmerged remote branches "
                "(no local copy found)?",
                choices=["Skip all", "Select which to delete", "Delete all"],
                default="Skip all",
            )
            match action:
                case "Delete all":
                    to_delete.extend(unmerged_no_local)
                case "Select which to delete":
                    to_delete.extend(
                        ui.ask_checkbox(
                            "Select unmerged remote branches to delete:",
                            choices=unmerged_no_local,
                        )
                    )

    if not to_delete:
        return True

    ui.print(f"\n🔥  Deleting {len(to_delete)} branches from origin...")
    try:
        # Atomic delete, stream output directly to terminal
        subprocess_run(
            ["git", "push", "origin", "--delete"] + to_delete,
            cwd=repo_path,
            check=True,
        )
        ui.print("\n✅  Remote cleanup complete.")
        return True
    except CalledProcessError as e:
        ui.print(f"❌  Error during deletion: {e}")
        return False
