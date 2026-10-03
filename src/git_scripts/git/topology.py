"""Git branch topology analyzer and graph state manager."""

import subprocess
from collections.abc import Callable, Sequence

import pygit2

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.parallel import analyze_branches_in_parallel
from git_scripts.git.reads import (
    find_cut_point,
    find_sync_point,
    find_tips,
    is_obsolete,
)
from git_scripts.models import RemotePushParityResult, TopologyAnalysisResult


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

    def analyze_obsolescence(
        self,
        target: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
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

        if progress_callback:
            progress_callback("Analyzing topology...")

        results = analyze_branches_in_parallel(
            repo_path=self.repo_path,
            branches=self.tips,
            target_ref=target,
            analyze_fn=_analyze,
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


def _get_commit_oid(
    repo: pygit2.Repository, ref_or_branch: str
) -> pygit2.Oid | None:
    """Resolves a branch or reference name to a pygit2.Oid if valid."""
    try:
        obj = repo.revparse_single(ref_or_branch)
    except (KeyError, ValueError, pygit2.GitError):
        return None
    commit_id = getattr(obj, "id", None)
    return commit_id if isinstance(commit_id, pygit2.Oid) else None


def _is_at_or_behind_stop_ref(
    repo: pygit2.Repository, branch: str, stop_at: str | None
) -> bool:
    """Returns True if branch is stop_at or at/behind stop_at's commit."""
    if not stop_at:
        return False
    if branch == stop_at:
        return True
    branch_oid = _get_commit_oid(repo, branch)
    if branch_oid is None:
        return False
    for ref_name in (stop_at, f"refs/remotes/origin/{stop_at}"):
        stop_oid = _get_commit_oid(repo, ref_name)
        if stop_oid is None:
            continue
        if branch_oid == stop_oid:
            return True
        if repo.merge_base(stop_oid, branch_oid) == branch_oid:
            return True
    return False


def check_remote_trunk_ancestry(
    repo: pygit2.Repository,
    bottom_branch: str,
    target: str,
    remote: str = "origin",
) -> bool:
    """Checks if the remote target is an ancestor of the bottom branch."""
    target_oid = _get_commit_oid(
        repo, f"refs/remotes/{remote}/{target}"
    ) or _get_commit_oid(repo, target)
    bottom_oid = _get_commit_oid(repo, bottom_branch)
    if target_oid is None or bottom_oid is None:
        return False
    return repo.merge_base(target_oid, bottom_oid) == target_oid


def check_stack_continuity(
    repo: pygit2.Repository, ordered_branches: list[str]
) -> tuple[bool, str | None]:
    """Checks if each branch is a strict descendant of the one below it.

    Returns (True, None) if continuous, or (False, broken_branch_name).
    """
    for b1, b2 in zip(ordered_branches, ordered_branches[1:], strict=False):
        oid1 = _get_commit_oid(repo, b1)
        oid2 = _get_commit_oid(repo, b2)
        if oid1 is None or oid2 is None or repo.merge_base(oid1, oid2) != oid1:
            return False, b2

    return True, None


def _classify_branch_push_state(
    repo: pygit2.Repository, branch: str, remote: str = "origin"
) -> str:
    """Classifies a branch as 'synced', 'unpushed', 'diverged', or 'behind'."""
    local_oid = _get_commit_oid(repo, branch)
    remote_oid = _get_commit_oid(repo, f"refs/remotes/{remote}/{branch}")
    if local_oid is None or remote_oid is None:
        return "unpushed"
    if local_oid == remote_oid:
        return "synced"

    try:
        merge_base_id = repo.merge_base(local_oid, remote_oid)
    except (KeyError, ValueError, TypeError, pygit2.GitError):
        return "unpushed"

    if merge_base_id == remote_oid:
        return "unpushed"
    return "behind" if merge_base_id == local_oid else "diverged"


def check_remote_push_parity(
    repo: pygit2.Repository,
    branches: Sequence[str] | set[str],
    remote: str = "origin",
) -> RemotePushParityResult:
    """Checks local branch hashes against their remote tracking branches."""
    ordered = sorted(branches) if isinstance(branches, set) else list(branches)
    unpushed: list[str] = []
    diverged: list[str] = []
    behind: list[str] = []

    for branch in ordered:
        match _classify_branch_push_state(repo, branch, remote=remote):
            case "unpushed":
                unpushed.append(branch)
            case "diverged":
                unpushed.append(branch)
                diverged.append(branch)
            case "behind":
                behind.append(branch)

    return RemotePushParityResult(
        unpushed_branches=tuple(unpushed),
        diverged_branches=tuple(diverged),
        behind_remote_branches=tuple(behind),
    )


def _compute_ancestor_distance(
    repo: pygit2.Repository,
    branch: str,
    branch_id: pygit2.Oid,
    candidate: str,
    cand_id: pygit2.Oid,
) -> float | None:
    """Returns topological distance from cand_id to branch_id if ancestor."""
    if repo.merge_base(cand_id, branch_id) != cand_id:
        return None
    if cand_id == branch_id:
        # Co-located branches: break ties lexicographically (< 1 commit).
        return 0.5 if candidate < branch else None

    walker = repo.walk(branch_id, pygit2.enums.SortMode.TOPOLOGICAL)
    walker.hide(cand_id)
    return float(sum(1 for _ in walker))


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

    for candidate in sorted(candidate_branches):
        if candidate == branch:
            continue
        try:
            cand_commit = repo.revparse_single(candidate)
        except (KeyError, ValueError):
            continue

        dist = _compute_ancestor_distance(
            repo, branch, branch_commit.id, candidate, cand_commit.id
        )
        if dist is not None and dist < min_dist:
            min_dist = dist
            parent = candidate

    return parent


def _find_direct_children(
    repo: pygit2.Repository,
    curr: str,
    pool: set[str],
    stack: set[str],
    stop_at: str | None,
) -> list[str]:
    """Finds direct child branches of curr in pool not behind stop_at."""
    effective_pool = set(pool) | ({stop_at} if stop_at else set())
    curr_oid = _get_commit_oid(repo, curr)
    children = []
    for branch in sorted(pool):
        if branch in stack or _is_at_or_behind_stop_ref(repo, branch, stop_at):
            continue
        parent = get_parent_branch(repo, branch, effective_pool)
        if not parent:
            continue
        if parent == curr or (
            curr_oid is not None and _get_commit_oid(repo, parent) == curr_oid
        ):
            children.append(branch)
    return children


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
    if _is_at_or_behind_stop_ref(repo, start_branch, stop_at):
        return set()

    effective_pool = set(pool) | ({stop_at} if stop_at else set())
    stack = {start_branch}

    # Walk up to ancestors
    curr = start_branch
    while True:
        parent = get_parent_branch(repo, curr, effective_pool)
        if not parent or _is_at_or_behind_stop_ref(repo, parent, stop_at):
            break
        stack.add(parent)
        curr = parent

    # Walk down to descendants along a strictly linear path
    curr = start_branch
    while True:
        children = _find_direct_children(repo, curr, pool, stack, stop_at)
        if not children:
            break
        distinct_oids = {
            oid
            for b in children
            if (oid := _get_commit_oid(repo, b)) is not None
        }
        if len(distinct_oids) > 1 or (not distinct_oids and len(children) > 1):
            break
        stack.update(children)
        curr = children[0]

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

    branch_to_children: dict[str, list[str]] = {b: [] for b in branches}
    roots = []

    for b in sorted(branches):
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


def sync_colocated_branches(
    repo: pygit2.Repository,
    branch: str,
    stack_refs: set[str],
    analyzer: TopologyAnalyzer,
    repo_path: str,
) -> None:
    """Fast-forward co-located alias branches sharing the exact same commit."""
    new_tip_commit = repo.revparse_single(branch)
    analyzer_old_commit_hash = analyzer.initial_ref_map.get(branch)
    new_id_str = str(new_tip_commit.id)

    if not analyzer_old_commit_hash or new_id_str == analyzer_old_commit_hash:
        return

    for ref in stack_refs:
        if ref == branch:
            continue
        ref_old_hash = analyzer.initial_ref_map.get(ref)
        if ref_old_hash == analyzer_old_commit_hash:
            try:
                run_cmd(
                    ["git", "branch", "-f", ref, new_id_str], cwd=repo_path
                )
            except GitExecutionError:
                pass
