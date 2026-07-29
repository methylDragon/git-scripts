"""Pygit2 queries and readonly operations."""

import subprocess
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple

import pygit2


def get_repo(path: str = ".") -> pygit2.Repository:
    """Returns a pygit2 Repository object."""
    return pygit2.Repository(pygit2.discover_repository(path))


def _get_patch_id(
    repo: pygit2.Repository, commit: pygit2.Commit
) -> Optional[pygit2.Oid]:
    """Calculates the patch ID for a single commit."""
    if not commit.parents:
        tree = commit.tree
        # Diff empty tree against commit tree
        diff = tree.diff_to_tree()
    else:
        diff = repo.diff(commit.parents[0].tree, commit.tree)
    return diff.patchid


@lru_cache(maxsize=128)
def _get_target_history_data(
    repo_path: str, target_commit_id: str, search_depth: int
) -> Tuple[Set[pygit2.Oid], Set[pygit2.Oid]]:
    """Caches target history tree IDs and patch IDs."""
    repo = pygit2.Repository(repo_path)
    target_commit = repo.get(target_commit_id)

    walker = repo.walk(target_commit.id, pygit2.GIT_SORT_TOPOLOGICAL)
    walker.simplify_first_parent()

    tree_ids = set()
    patch_ids = set()

    for i, c in enumerate(walker):
        if i > search_depth:
            break
        tree_ids.add(c.tree.id)
        pid = _get_patch_id(repo, c)
        if pid:
            patch_ids.add(pid)

    return tree_ids, patch_ids


@lru_cache(maxsize=1024)
def _is_obsolete_cached(
    repo_path: str, commit_hash: str, target_ref: str, search_depth: int
) -> bool:
    """Cached version of obsolete check using subprocesses."""
    if repo_path.endswith("/.git/") or repo_path.endswith("/.git"):
        repo_path = repo_path[:-5]

    try:
        cherry = subprocess.run(
            ["git", "cherry", target_ref, commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        if not any(
            line.startswith("+") for line in cherry.stdout.splitlines()
        ):
            return True
    except subprocess.CalledProcessError:
        pass

    try:
        target_tree = subprocess.run(
            ["git", "rev-parse", f"{target_ref}^{{tree}}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        merge_tree = subprocess.run(
            ["git", "merge-tree", "--write-tree", target_ref, commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

        if merge_tree == target_tree:
            return True
    except subprocess.CalledProcessError:
        pass

    # Strategy 3: Tree Hash Match in History
    try:
        commit_tree = subprocess.run(
            ["git", "rev-parse", f"{commit_hash}^{{tree}}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        target_history_trees = subprocess.run(
            [
                "git",
                "log",
                f"--max-count={search_depth}",
                "--pretty=%T",
                target_ref,
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

        if commit_tree in target_history_trees:
            return True
    except subprocess.CalledProcessError:
        pass

    return False


def is_obsolete(
    repo: pygit2.Repository,
    commit_oid: pygit2.Oid,
    target_ref: str,
    search_depth: int = 100,
) -> bool:
    """Checks if a commit is content-equivalent to upstream using git subprocesses for speed."""  # noqa: E501
    return _is_obsolete_cached(
        repo.path, str(commit_oid), target_ref, search_depth
    )


def find_tips(repo: pygit2.Repository, branches: List[str]) -> List[str]:
    """Finds tip branches (branches that are not ancestors of another)."""
    tips = []

    for branch in branches:
        is_tip = True
        branch_commit = repo.revparse_single(branch)
        for other_branch in branches:
            if branch == other_branch:
                continue
            other_commit = repo.revparse_single(other_branch)

            # Check if branch is ancestor of other_branch
            if (
                repo.merge_base(branch_commit.id, other_commit.id)
                == branch_commit.id
            ):
                is_tip = False
                break

        if is_tip:
            tips.append(branch)

    # Sort for deterministic output
    return sorted(set(tips))


def find_cut_point(
    repo: pygit2.Repository,
    tip_hash: str,
    target_ref: str,
    search_depth: int = 100,
) -> Optional[str]:
    """Finds the boundary commit where a local branch diverges from merged.

    Uses `git cherry` internally to get the patch equivalence of all commits
    in one highly-optimized batch call. Falls back to `merge-tree` only when
    squash merges are suspected.
    """
    repo_path = repo.path
    if repo_path.endswith("/.git/") or repo_path.endswith("/.git"):
        repo_path = repo_path[:-5]

    try:
        cherry = subprocess.run(
            ["git", "cherry", target_ref, tip_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    # Map commit hashes to their patch-id equivalence status ('-' or '+')
    status_map = {}
    for line in cherry.stdout.splitlines():
        if line:
            status, sha = line.split()
            status_map[sha] = status

    tip_commit = repo.revparse_single(tip_hash)
    target_commit = repo.revparse_single(target_ref)

    walker = repo.walk(tip_commit.id, pygit2.GIT_SORT_TOPOLOGICAL)
    walker.hide(target_commit.id)

    target_tree = None

    for i, commit in enumerate(walker):
        if i > search_depth:
            break

        sha = str(commit.id)
        status = status_map.get(sha, "")

        if status == "-":
            # Native patch-ID match found
            return sha
        else:
            # If it's '+' (or missing), it might still be a squash merge.
            # We run `merge-tree` to verify.
            if target_tree is None:
                try:
                    target_tree = subprocess.run(
                        ["git", "rev-parse", f"{target_ref}^{{tree}}"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout.strip()
                except subprocess.CalledProcessError:
                    return None

            try:
                merge_tree = subprocess.run(
                    ["git", "merge-tree", "--write-tree", target_ref, sha],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()

                if merge_tree == target_tree:
                    return sha
            except subprocess.CalledProcessError:
                pass

    return None


def find_sync_point(
    repo: pygit2.Repository,
    branch: str,
    all_branches: List[str],
    initial_ref_map: Dict[str, str],
) -> Optional[Tuple[str, str, str]]:
    """Finds closest ancestor of the branch that has already been rebased.

    Returns: (sync_branch_name, old_hash, new_hash)
    """
    branch_commit = repo.revparse_single(branch)

    sync_branch = None
    sync_old_hash = None
    sync_new_hash = None
    best_dist = 999999

    for candidate in all_branches:
        if candidate == branch:
            continue

        candidate_initial_hash = initial_ref_map[candidate]
        candidate_initial_commit = repo.get(candidate_initial_hash)
        if not candidate_initial_commit:
            continue

        # 1. Check Ancestry using SNAPSHOT hashes
        if (
            repo.merge_base(candidate_initial_hash, branch_commit.id)
            == candidate_initial_commit.id
        ):
            # 2. Check for movement
            candidate_curr_commit = repo.revparse_single(candidate)
            if str(candidate_curr_commit.id) != candidate_initial_hash:
                # 3. Calculate Distance using initial hashes
                # We count commits between candidate_initial and branch
                # Not very trivial in pygit2 without walking, so we walk:
                walker = repo.walk(
                    branch_commit.id, pygit2.GIT_SORT_TOPOLOGICAL
                )
                walker.hide(candidate_initial_commit.id)
                dist = sum(1 for _ in walker)

                if dist < best_dist:
                    best_dist = dist
                    sync_branch = candidate
                    sync_old_hash = candidate_initial_hash
                    sync_new_hash = str(candidate_curr_commit.id)

    if sync_branch and sync_old_hash and sync_new_hash:
        return (sync_branch, sync_old_hash, sync_new_hash)
    return None


def get_stack_refs(
    repo: pygit2.Repository,
    tip_name: str,
    prefix: str = "",
    merged_in_target: Optional[str] = None,
) -> Set[str]:
    """Helper to get branches merged into a specific tip/target."""
    tip_commit = repo.revparse_single(tip_name)
    refs = set()
    for ref in repo.references:
        if not ref.startswith("refs/heads/"):
            continue
        short_name = ref[11:]
        if prefix and not short_name.startswith(prefix):
            continue

        try:
            ref_commit = repo.revparse_single(ref)
            if repo.merge_base(ref_commit.id, tip_commit.id) == ref_commit.id:
                refs.add(short_name)
        except (KeyError, ValueError, TypeError):
            continue
    return refs


def format_stack_tree(
    repo: pygit2.Repository,
    tip: str,
    prefix: str = "",
    target: str = "",
    filter_merged_in_target: bool = False,
    allowed_refs: Optional[Set[str]] = None,
) -> str:
    """Generates a visual tree string for the stack."""
    stack_refs = get_stack_refs(repo, tip, prefix)

    target_refs = set()
    if filter_merged_in_target and target:
        target_refs = get_stack_refs(repo, target, prefix)

    children = []
    for ref in stack_refs:
        if ref == tip:
            continue
        if allowed_refs is not None and ref not in allowed_refs:
            continue
        if filter_merged_in_target and ref in target_refs:
            continue
        children.append(ref)

    # Sort children by distance to tip
    tip_commit = repo.revparse_single(tip)

    def get_distance(child_ref):
        try:
            child_commit = repo.revparse_single(child_ref)
            walker = repo.walk(tip_commit.id, pygit2.GIT_SORT_TOPOLOGICAL)
            walker.hide(child_commit.id)
            return sum(1 for _ in walker)
        except (KeyError, ValueError, TypeError):
            return 999999

    children.sort(key=get_distance)

    tree = tip
    count = len(children)
    for i, child in enumerate(children):
        if i == count - 1:
            tree += f"\n    └─ {child}"
        else:
            tree += f"\n    ├─ {child}"

    return tree
