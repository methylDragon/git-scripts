"""Parallel execution utilities for Git branch analysis."""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

import pygit2

T = TypeVar("T")


def _count_branch_commits(
    repo: pygit2.Repository | None,
    target_oid: pygit2.Oid | None,
    branch: str,
) -> int:
    """Returns the commit count in target_oid..branch (minimum weight 1)."""
    if repo is None or target_oid is None:
        return 1
    try:
        branch_oid = repo.revparse_single(branch).peel(pygit2.Commit).id
        if (
            branch_oid == target_oid
            or repo.merge_base(target_oid, branch_oid) == branch_oid
        ):
            return 1
        walker = repo.walk(branch_oid, pygit2.enums.SortMode.TOPOLOGICAL)
        walker.hide(target_oid)
        return max(1, sum(1 for _ in walker))
    except (KeyError, ValueError, TypeError, pygit2.GitError):
        return 1


def _compute_branch_weights(
    repo_path: str, branches: list[str], target_ref: str
) -> dict[str, int]:
    """Computes commit weights per branch relative to target_ref."""
    repo: pygit2.Repository | None = None
    target_oid: pygit2.Oid | None = None
    try:
        repo = pygit2.Repository(repo_path)
        target_oid = repo.revparse_single(target_ref).peel(pygit2.Commit).id
    except (KeyError, ValueError, TypeError, pygit2.GitError):
        pass

    return {b: _count_branch_commits(repo, target_oid, b) for b in branches}


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

    counts: dict[str, int] = (
        _compute_branch_weights(repo_path, branch_list, target_ref)
        if (on_start or on_progress)
        else {}
    )

    if on_start:
        on_start(sum(counts.values()))

    results: dict[str, T] = {}

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
