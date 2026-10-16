"""Core logic for pushing local branches matching a prefix."""

import pygit2

from git_scripts.cmd.shared import (
    partition_out_of_sync_branches,
    print_available_prefixes_hint,
    resolve_branches_to_push,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.remote import push_branches
from git_scripts.ui import UI


def _get_out_of_sync_branches(
    repo: pygit2.Repository, prefix: str
) -> tuple[list[str], int]:
    """Finds local branches matching prefix that differ from remote."""
    matching = [
        ref[len("refs/heads/") :]
        for ref in repo.references
        if ref.startswith(f"refs/heads/{prefix}")
    ]
    return partition_out_of_sync_branches(repo, matching)


def execute_push_prefix(
    repo_path: str,
    prefix: str,
    push_opts: list[str] | None = None,
    ui: UI | None = None,
) -> bool:
    """Pushes out-of-sync local branches matching the prefix to the remote."""
    if ui is None:
        ui = UI()

    if not prefix or not prefix.strip():
        ui.print(
            "❌  Error: Missing <prefix>. Pass --prefix (-p) <pfx> "
            "(e.g. 'git batch push -p feat/')."
        )
        return False

    if push_opts is None:
        push_opts = []

    repo = pygit2.Repository(repo_path)

    ui.print("[cyan]🔄  Fetching origin...[/cyan]")
    # Shell out for fetch to handle auth natively
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_path)
    except GitExecutionError:
        pass

    ui.print(f"[cyan]🔍  Scanning 'refs/heads/{prefix}*'...[/cyan]")

    branches_to_push, up_to_date_count = _get_out_of_sync_branches(
        repo, prefix
    )

    is_dry_run = any(opt in ("-n", "--dry-run") for opt in push_opts)
    resolved_branches = resolve_branches_to_push(
        branches=branches_to_push,
        ui=ui,
        dry_run=is_dry_run,
    )

    if not resolved_branches:
        if up_to_date_count > 0:
            ui.print(
                f"✅  {ui.pluralize(up_to_date_count, 'branch')} already "
                "up-to-date. No branches to push."
            )
        elif not branches_to_push:
            ui.print("  [yellow]No matching branches found.[/yellow]")
            print_available_prefixes_hint(repo, ui)
        return True

    return push_branches(
        branches=resolved_branches,
        options=push_opts,
        repo_path=repo_path,
    )
