"""Parallel execution utilities for Git branch analysis."""

import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

from rich.progress import Progress

T = TypeVar("T")


def analyze_branches_in_parallel(
    repo_path: str,
    branches: Iterable[str],
    target_ref: str,
    analyze_fn: Callable[[str], T],
    description: str = "Analyzing branches",
    ui=None,
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
        description: Text to display on the progress bar.
        ui: Optional UI object for progress rendering.

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

    with ThreadPoolExecutor() as executor:
        futures = {}
        for b in branch_list:
            futures[
                executor.submit(
                    subprocess.run,
                    ["git", "rev-list", "--count", f"{target_ref}..{b}"],
                    cwd=repo_cwd,
                    capture_output=True,
                    text=True,
                )
            ] = b

        for f in as_completed(futures):
            b = futures[f]
            try:
                # Assign a minimum weight of 1 for completely merged branches
                counts[b] = max(1, int(f.result().stdout.strip()))
            except Exception:
                counts[b] = 1
            total_commits += counts[b]

    results = {}

    if ui and not ui.plain:
        with Progress(console=ui.console, transient=True) as progress:
            task = progress.add_task(
                f"[cyan]{description}...", total=total_commits
            )
            with ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(analyze_fn, b): b for b in branch_list
                }
                for f in as_completed(futures):
                    b = futures[f]
                    # Update description
                    short_b = b.replace("refs/remotes/origin/", "")
                    progress.update(
                        task, description=f"[cyan]{description}: {short_b}"
                    )
                    results[b] = f.result()
                    progress.advance(task, advance=counts[b])
    else:
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(analyze_fn, b): b for b in branch_list}
            for f in as_completed(futures):
                results[futures[f]] = f.result()

    return results
