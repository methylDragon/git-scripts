"""Git branch topology analyzer and graph state manager."""

import subprocess

import pygit2

from git_scripts.git.parallel import analyze_branches_in_parallel
from git_scripts.git.reads import (
    find_cut_point,
    find_sync_point,
    find_tips,
    is_obsolete,
)
from git_scripts.models import TopologyAnalysisResult


class TopologyAnalyzer:
    """Analyzes and caches Git repository branch topology and obsolescence.

    This class is responsible for holding the static branch state (like
    the initial hashes of branches before any operations) and providing
    high-level methods to query the graph, such as finding tips, cut
    points, and sync points.
    """

    def __init__(self, repo_path: str, branches: list[str]):
        """Initializes the analyzer with a repository and a set of branches.

        Args:
            repo_path: Path to the git repository.
            branches: A list of local branch names to analyze.
        """
        self.repo_path = repo_path
        self.repo = pygit2.Repository(repo_path)
        self.branches = branches

        # Precompute initial hashes to track movement during rebases
        self.initial_ref_map: dict[str, str] = {}
        for b in branches:
            try:
                self.initial_ref_map[b] = str(self.repo.revparse_single(b).id)
            except (KeyError, ValueError, pygit2.GitError):
                pass

        self.tips: list[str] = find_tips(self.repo, self.branches)

        # Cache for expensive analysis
        self._analysis_cache: dict[str, TopologyAnalysisResult] = {}

    def get_sync_point(self, branch: str) -> tuple[str, str, str] | None:
        """Finds closest ancestor of the branch that has already been rebased.

        Returns:
            (sync_branch_name, old_hash, new_hash) if found, else None.
        """
        return find_sync_point(
            self.repo, branch, self.branches, self.initial_ref_map
        )

    def analyze_obsolescence(self, target: str, ui=None) -> None:
        """Precomputes obsolescence and cut points for all stack tips.

        Evaluates each branch tip against the upstream target branch history
        to check if its patches were squashed or merged. The results are
        cached for fast subsequent retrieval during batch stack operations.
        """

        def _analyze(b_name: str):
            local_repo = pygit2.Repository(self.repo_path)
            try:
                commit_id = local_repo.revparse_single(b_name).id
            except (KeyError, ValueError, pygit2.GitError):
                return False, None

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
                obs = is_obsolete(local_repo, commit_id, target)
                cut = None
                if not obs:
                    cut = find_cut_point(local_repo, str(commit_id), target)
            return obs, cut

        results = analyze_branches_in_parallel(
            repo_path=self.repo_path,
            branches=self.tips,
            target_ref=target,
            analyze_fn=_analyze,
            description="Analyzing topology",
            ui=ui,
        )

        for b_name, (obs, cut) in results.items():
            self._analysis_cache[b_name] = TopologyAnalysisResult(
                is_obsolete=obs,
                cut_point=cut,
            )

    def get_analysis(self, branch: str) -> TopologyAnalysisResult:
        """Gets the precomputed analysis for a tip branch."""
        return self._analysis_cache.get(
            branch, TopologyAnalysisResult(is_obsolete=False, cut_point=None)
        )


def check_remote_trunk_ancestry(
    repo: pygit2.Repository, bottom_branch: str, target: str
) -> bool:
    """Checks if the remote target is an ancestor of the bottom branch."""
    remote_target_ref = f"refs/remotes/origin/{target}"
    try:
        target_commit = repo.revparse_single(remote_target_ref)
    except (KeyError, ValueError):
        try:
            target_commit = repo.revparse_single(target)
        except (KeyError, ValueError):
            return False

    try:
        bottom_commit = repo.revparse_single(bottom_branch)
    except (KeyError, ValueError):
        return False

    return (
        repo.merge_base(target_commit.id, bottom_commit.id) == target_commit.id
    )


def check_stack_continuity(
    repo: pygit2.Repository, ordered_branches: list[str]
) -> tuple[bool, str | None]:
    """Checks if each branch is a strict descendant of the one below it.

    Returns (True, None) if continuous, or (False, broken_branch_name).
    """
    for i in range(len(ordered_branches) - 1):
        b1 = ordered_branches[i]
        b2 = ordered_branches[i + 1]
        try:
            c1 = repo.revparse_single(b1)
            c2 = repo.revparse_single(b2)
        except (KeyError, ValueError):
            return False, b2

        if repo.merge_base(c1.id, c2.id) != c1.id:
            return False, b2

    return True, None


def check_remote_push_parity(
    repo: pygit2.Repository, branches: set[str]
) -> tuple[bool, str | None]:
    """Checks if local branch hashes exactly match remote tracking branches.

    Returns (True, None) if all match, or (False, unpushed_branch_name).
    """
    for branch in sorted(branches):
        try:
            local_commit = repo.revparse_single(branch)
        except (KeyError, ValueError):
            return False, branch

        remote_ref = f"refs/remotes/origin/{branch}"
        try:
            remote_commit = repo.revparse_single(remote_ref)
        except (KeyError, ValueError):
            return False, branch

        if local_commit.id != remote_commit.id:
            return False, branch

    return True, None


def get_parent_branch(
    repo: pygit2.Repository, branch: str, candidate_branches: set[str]
) -> str | None:
    """Finds the closest direct ancestor among the candidate branches."""
    try:
        branch_commit = repo.revparse_single(branch)
    except (KeyError, ValueError):
        return None

    parent = None
    min_dist = float("inf")

    for candidate in candidate_branches:
        if candidate == branch:
            continue
        try:
            cand_commit = repo.revparse_single(candidate)
        except (KeyError, ValueError):
            continue

        if repo.merge_base(cand_commit.id, branch_commit.id) == cand_commit.id:
            walker = repo.walk(
                branch_commit.id, pygit2.enums.SortMode.TOPOLOGICAL
            )
            walker.hide(cand_commit.id)
            dist = sum(1 for _ in walker)
            if 0 < dist < min_dist:
                min_dist = dist
                parent = candidate

    return parent


def find_linear_stack(
    repo: pygit2.Repository,
    start_branch: str,
    pool: set[str],
    stop_at: str | None = None,
) -> set[str]:
    """Finds the full linear stack containing start_branch within the pool.

    This traverses both ancestors (up to stop_at) and descendants
    (up to the tip) to discover the complete stack.
    """
    stack = {start_branch}

    # Walk up to ancestors
    curr = start_branch
    while True:
        parent = get_parent_branch(repo, curr, pool)
        if not parent:
            break
        if stop_at and parent == stop_at:
            break
        stack.add(parent)
        curr = parent

    # Walk down to descendants
    curr = start_branch
    while True:
        child = None
        for b in pool:
            if b not in stack and get_parent_branch(repo, b, pool) == curr:
                child = b
                break

        if not child:
            break
        stack.add(child)
        curr = child

    return stack


def sort_branches_bottom_to_top(
    branches: set[str], parent_map: dict[str, str | None]
) -> list[str]:
    """Sorts a set of branches from bottom-most (ancestor) to top-most."""
    ordered = []

    # We find the branch whose parent is NOT in the set of branches
    # This is our bottom-most branch. Then we follow the children up.
    # Note: If there are multiple disjoint stacks, this might need
    # to handle multiple roots, but typically we operate on a linear stack.

    branch_to_children = {b: [] for b in branches}
    roots = []

    for b in branches:
        p = parent_map.get(b)
        if p in branches:
            branch_to_children[p].append(b)
        else:
            roots.append(b)

    # Simple BFS/DFS to build the ordered list
    queue = roots.copy()
    while queue:
        curr = queue.pop(0)
        ordered.append(curr)
        queue.extend(branch_to_children.get(curr, []))

    return ordered
