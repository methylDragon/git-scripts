"""Core logic for pruning obsolete remote branches by prefix."""

import time
from subprocess import CalledProcessError
from subprocess import run as subprocess_run

import pygit2

from git_scripts.cmd.shared import (
    BranchProgressTracker,
    print_available_prefixes_hint,
    print_two_bucket_prune_summary,
    select_branches_to_delete,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.parallel import analyze_branches_in_parallel
from git_scripts.git.reads import get_repo, is_obsolete
from git_scripts.models import RemotePruneResult
from git_scripts.ui import UI


def _collect_remote_prefix_candidates(
    repo: pygit2.Repository,
    prefix: str,
    target: str,
    *,
    also_prune_no_local: bool,
) -> tuple[list[str], set[str]]:
    """Collects matching remote refs and orphaned remote refs."""
    local_branches = set(repo.branches.local)
    refs_to_check: list[str] = []
    orphaned_remotes: set[str] = set()
    remote_prefix = f"refs/remotes/origin/{prefix}"
    skipped_refs = (
        "refs/remotes/origin/HEAD",
        f"refs/remotes/origin/{target}",
    )

    for ref in repo.references:
        if not ref.startswith(remote_prefix) or ref in skipped_refs:
            continue
        short_name = ref[len("refs/remotes/origin/") :]
        if also_prune_no_local and short_name not in local_branches:
            orphaned_remotes.add(ref)
        refs_to_check.append(ref)
    return refs_to_check, orphaned_remotes


def _find_obsolete_remote_branches(
    repo_path: str,
    prefix: str,
    target: str,
    also_prune_no_local: bool,
    ui: UI,
) -> RemotePruneResult:
    """Scans and analyzes remote branches to find obsolete ones."""
    ui.print(
        f"[dim]🔍  Scanning 'origin/{prefix}*' for obsolete branches...[/dim]"
    )
    start_time = time.monotonic()
    repo = get_repo(repo_path)
    refs_to_check, orphaned_remotes = _collect_remote_prefix_candidates(
        repo, prefix, target, also_prune_no_local=also_prune_no_local
    )

    def _check_obs(ref_name: str) -> bool:
        local_repo = get_repo(repo_path)
        commit_id = local_repo.revparse_single(ref_name).id
        return is_obsolete(
            local_repo,
            commit_id,
            f"refs/remotes/origin/{target}",
        )

    with BranchProgressTracker(ui, "Analyzing obsolescence") as tracker:
        results = analyze_branches_in_parallel(
            repo_path=repo_path,
            branches=refs_to_check,
            target_ref=f"refs/remotes/origin/{target}",
            analyze_fn=_check_obs,
            on_start=tracker.on_start,
            on_progress=tracker.on_progress,
        )

    obsolete_branches: list[str] = []
    unmerged_no_local_branches: list[str] = []
    for ref, obsolete in results.items():
        short_name = ref[len("refs/remotes/origin/") :]
        if obsolete:
            obsolete_branches.append(short_name)
        elif ref in orphaned_remotes:
            unmerged_no_local_branches.append(short_name)

    elapsed = time.monotonic() - start_time
    ui.print(
        f"  [dim]⏱️  Remote obsolescence scan completed in {elapsed:.2f}s[/dim]"
    )
    return RemotePruneResult(
        obsolete_branches=obsolete_branches,
        unmerged_no_local_branches=unmerged_no_local_branches,
    )


def _print_prune_remote_summary(
    obsolete_branches: list[str],
    unmerged_no_local: list[str],
    ui: UI,
) -> None:
    """Prints panels summarizing obsolete and unmerged remote branches."""
    unmerged_count = len(unmerged_no_local)
    print_two_bucket_prune_summary(
        obsolete_branches,
        f"Found {len(obsolete_branches)} obsolete remote branches",
        unmerged_no_local,
        f"Found {unmerged_count} unmerged branches lacking local counterparts",
        ui,
    )


def execute_prune_remote_prefix(
    repo_path: str,
    prefix: str,
    target: str = "main",
    dry_run: bool = False,
    also_prune_no_local: bool = False,
    ui: UI | None = None,
) -> bool:
    """Prunes obsolete remote branches that match a prefix."""
    if ui is None:
        ui = UI()

    if not prefix or not prefix.strip():
        ui.print(
            "❌  Error: Missing <prefix>. Pass --prefix (-p) <pfx> "
            "(e.g. 'git batch prune remote -p feat/ --dry-run')."
        )
        return False

    if dry_run:
        ui.print("Running git batch prune remote in dry-run mode...")

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
        repo_path, prefix, target, also_prune_no_local, ui
    )

    obsolete_branches = prune_result.obsolete_branches
    unmerged_no_local = prune_result.unmerged_no_local_branches

    if not obsolete_branches and not unmerged_no_local:
        ui.print("✅  No remote branches found for pruning.")
        if not any(
            ref.startswith(f"refs/remotes/origin/{prefix}")
            for ref in repo.references
        ):
            print_available_prefixes_hint(repo, ui, remote=True)
        return True

    _print_prune_remote_summary(obsolete_branches, unmerged_no_local, ui)

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
    to_delete: list[str] = []

    if obsolete_branches:
        obsolete_label = ui.pluralize(
            len(obsolete_branches), "obsolete remote branch"
        )
        to_delete.extend(
            select_branches_to_delete(
                obsolete_branches,
                f"❓  Delete {obsolete_label}?",
                "Select obsolete remote branches to delete:",
                ui,
                default="Delete all",
            )
        )

    if unmerged_no_local:
        to_delete.extend(
            select_branches_to_delete(
                unmerged_no_local,
                f"⚠️  Delete {len(unmerged_no_local)} unmerged remote branches "
                "(no local copy found)?",
                "Select unmerged remote branches to delete:",
                ui,
                default="Skip all",
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
