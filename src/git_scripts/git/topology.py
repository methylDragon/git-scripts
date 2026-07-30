"""Git branch topology analyzer and graph state manager."""

import subprocess
from typing import Dict, List, Optional, Tuple

import pygit2
from rich.progress import Progress

from git_scripts.git.reads import (
    find_cut_point,
    find_sync_point,
    find_tips,
    is_obsolete,
)


class TopologyAnalyzer:
    """Analyzes and caches Git repository branch topology and obsolescence.

    This class is responsible for holding the static branch state (like
    the initial hashes of branches before any operations) and providing
    high-level methods to query the graph, such as finding tips, cut
    points, and sync points.
    """

    def __init__(self, repo_path: str, branches: List[str]):
        """Initializes the analyzer with a repository and a set of branches.

        Args:
            repo_path: Path to the git repository.
            branches: A list of local branch names to analyze.
        """
        self.repo_path = repo_path
        self.repo = pygit2.Repository(repo_path)
        self.branches = branches

        # Precompute initial hashes to track movement during rebases
        self.initial_ref_map: Dict[str, str] = {}
        for b in branches:
            try:
                self.initial_ref_map[b] = str(self.repo.revparse_single(b).id)
            except (KeyError, ValueError, pygit2.GitError):
                pass

        self.tips: List[str] = find_tips(self.repo, self.branches)

        # Cache for expensive analysis
        self._analysis_cache: Dict[str, Dict[str, any]] = {}

    def get_sync_point(self, branch: str) -> Optional[Tuple[str, str, str]]:
        """Finds closest ancestor of the branch that has already been rebased.

        Returns:
            (sync_branch_name, old_hash, new_hash) if found, else None.
        """
        return find_sync_point(
            self.repo, branch, self.branches, self.initial_ref_map
        )

    def analyze_obsolescence(
        self, target: str, search_depth: int = 100, ui=None
    ) -> None:
        """Precomputes obsolescence and cut points for all stack tips.

        Evaluates each branch tip against the upstream target branch history
        (up to search_depth commits) to check if its patches were squashed or
        merged. The results are cached for fast subsequent retrieval during
        batch stack operations.
        """

        def _analyze(b_name: str):
            local_repo = pygit2.Repository(self.repo_path)
            try:
                commit_id = local_repo.revparse_single(b_name).id
            except (KeyError, ValueError, pygit2.GitError):
                return b_name, False, None

            # If the branch has no unique commits (it is an ancestor of
            # target), we shouldn't skip it as obsolete; we want
            # rebase_standard to fast-forward it to the target branch.
            try:
                has_unique_commits = bool(
                    subprocess.run(
                        ["git", "rev-list", f"{target}..{commit_id}"],
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout.strip()
                )
            except subprocess.CalledProcessError:
                has_unique_commits = True

            if not has_unique_commits:
                obs = False
                cut = None
            else:
                obs = is_obsolete(
                    local_repo,
                    commit_id,
                    target,
                    search_depth=search_depth,
                )
                cut = None
                if not obs:
                    cut = find_cut_point(
                        local_repo,
                        str(commit_id),
                        target,
                        search_depth=search_depth,
                    )
            return b_name, obs, cut

        if ui and not ui.plain:
            with Progress(console=ui.console, transient=True) as progress:
                task = progress.add_task(
                    "[cyan]Analyzing topology...", total=len(self.tips)
                )
                for b in self.tips:
                    progress.update(
                        task, description=f"[cyan]Analyzing topology: {b}"
                    )
                    b_name, obs, cut = _analyze(b)
                    self._analysis_cache[b_name] = {
                        "is_obs": obs,
                        "cut_point": cut,
                    }
                    progress.advance(task)
        else:
            for b in self.tips:
                b_name, obs, cut = _analyze(b)
                self._analysis_cache[b_name] = {
                    "is_obs": obs,
                    "cut_point": cut,
                }

    def get_analysis(self, branch: str) -> Dict[str, any]:
        """Gets the precomputed analysis for a tip branch."""
        return self._analysis_cache.get(
            branch, {"is_obs": False, "cut_point": None}
        )
