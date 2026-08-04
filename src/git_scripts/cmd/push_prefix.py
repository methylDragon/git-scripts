"""Core logic for the git-push-prefix command."""

import pygit2

from git_scripts.git.writes import (
    GitExecutionError,
    prompt_and_push_branches,
    run_cmd,
)
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
    # Shell out for fetch to handle auth natively
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_path)
    except GitExecutionError:
        pass

    ui.print(f"[cyan]🔍  Scanning 'refs/heads/{prefix}*'...[/cyan]")

    branches_to_push, up_to_date_count = _get_out_of_sync_branches(
        repo, prefix
    )

    return prompt_and_push_branches(
        branches=branches_to_push,
        ui=ui,
        push_opts=push_opts,
        repo_path=repo_path,
        skipped_count=up_to_date_count,
    )
