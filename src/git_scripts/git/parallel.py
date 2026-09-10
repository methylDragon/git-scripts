"""Parallel execution utilities for Git branch analysis."""

import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")


def analyze_branches_in_parallel(
    repo_path: str,
    branches: Iterable[str],
    target_ref: str,
    analyze_fn: Callable[[str], T],
    on_start: Callable[[int], None] | None = None,
    on_progress: Callable[[str, int], None] | None = None,
) -> dict[str, T]:
    """Runs a branch analysis function in parallel with proportional progress.

    1. Fetches commit counts for all branches relative to the target.
    2. Initializes a rich progress bar scaled to total commits.
    3. Runs `analyze_fn` concurrently, advancing the bar by branch weight.

    Args:
        repo_path: Path to the Git repository.
        branches: Iterable of branch names/refs to analyze.
        target_ref: The upstream ref (e.g., 'main' or 'origin/main').
        analyze_fn: Function that takes a branch name and returns a result.
        on_start: Optional callback to receive total commits for progress.
        on_progress: Optional callback to receive branch and commit count.

    Returns:
        A dictionary mapping branch names to their analysis results.
    """
    branch_list = list(branches)
    if not branch_list:
        return {}

    # Strip trailing /.git if present
    repo_cwd = repo_path
    if repo_cwd.endswith("/.git/") or repo_cwd.endswith("/.git"):
        repo_cwd = repo_cwd[:-5]

    counts = {}
    total_commits = 0

    with ThreadPoolExecutor() as count_executor:
        count_futures = {}
        for b in branch_list:
            count_futures[
                count_executor.submit(
                    subprocess.run,
                    ["git", "rev-list", "--count", f"{target_ref}..{b}"],
                    cwd=repo_cwd,
                    capture_output=True,
                    text=True,
                )
            ] = b

        for f in as_completed(count_futures):
            b = count_futures[f]
            try:
                # Assign a minimum weight of 1 for completely merged branches
                counts[b] = max(1, int(f.result().stdout.strip()))
            except Exception:
                counts[b] = 1
            total_commits += counts[b]

    results: dict[str, T] = {}

    if on_start:
        on_start(total_commits)

    with ThreadPoolExecutor() as analyze_executor:
        analyze_futures = {
            analyze_executor.submit(analyze_fn, b): b for b in branch_list
        }
        for f in as_completed(analyze_futures):
            b = analyze_futures[f]
            results[b] = f.result()
            if on_progress:
                on_progress(b, counts[b])

    return results
