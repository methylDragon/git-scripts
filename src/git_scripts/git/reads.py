"""Pygit2 queries and readonly operations."""

import subprocess
from functools import lru_cache

import pygit2


def get_repo(path: str = ".") -> pygit2.Repository:
    """Returns an initialized PyGit2 repository."""
    return pygit2.Repository(pygit2.discover_repository(path))


def _check_squash_merge(
    repo_path: str,
    commit_hash: str,
    target_ref: str,
    target_tree: str | None = None,
) -> bool:
    """Returns True if commit_hash is squash-merged into target_ref."""
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
            return False

    try:
        merge_tree = subprocess.run(
            ["git", "merge-tree", "--write-tree", target_ref, commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

        return merge_tree == target_tree
    except subprocess.CalledProcessError:
        return False


@lru_cache(maxsize=1024)
def _is_obsolete_cached(
    repo_path: str, commit_hash: str, target_ref: str
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

    if _check_squash_merge(repo_path, commit_hash, target_ref):
        return True

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
                "--pretty=%T",
                f"{commit_hash}..{target_ref}",
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
) -> bool:
    """Checks if a commit is content-equivalent to upstream.

    Uses git subprocesses for speed.
    """
    return _is_obsolete_cached(repo.path, str(commit_oid), target_ref)


def find_tips(repo: pygit2.Repository, branches: list[str]) -> list[str]:
    """Returns branches that are not ancestors of any other in the list."""
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
) -> str | None:
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

    walker = repo.walk(tip_commit.id, pygit2.enums.SortMode.TOPOLOGICAL)
    walker.hide(target_commit.id)

    target_tree = None

    for commit in walker:
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

            if _check_squash_merge(repo_path, sha, target_ref, target_tree):
                return sha

    return None


def find_sync_point(
    repo: pygit2.Repository,
    branch: str,
    all_branches: list[str],
    initial_ref_map: dict[str, str],
) -> tuple[str, str, str] | None:
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
                    branch_commit.id, pygit2.enums.SortMode.TOPOLOGICAL
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


def get_stack_branches(
    repo: pygit2.Repository,
    tip_name: str,
    prefix: str = "",
    merged_in_target: str | None = None,
) -> set[str]:
    """Returns local branches fully merged into the specified tip/target."""
    tip_commit = repo.revparse_single(tip_name)
    branches = set()
    for ref in repo.references:
        if not ref.startswith("refs/heads/"):
            continue
        short_name = ref[11:]
        if prefix and not short_name.startswith(prefix):
            continue

        try:
            ref_commit = repo.revparse_single(ref)
            if repo.merge_base(ref_commit.id, tip_commit.id) == ref_commit.id:
                branches.add(short_name)
        except (KeyError, ValueError, TypeError):
            continue
    return branches


def format_stack_tree(
    repo: pygit2.Repository,
    tip: str,
    prefix: str = "",
    target: str = "",
    filter_merged_in_target: bool = False,
    allowed_refs: set[str] | None = None,
) -> str:
    """Generates an ASCII hierarchy tree representing the branch stack."""
    stack_refs = get_stack_branches(repo, tip, prefix)

    target_refs = set()
    if filter_merged_in_target and target:
        target_refs = get_stack_branches(repo, target, prefix)

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
            walker = repo.walk(
                tip_commit.id, pygit2.enums.SortMode.TOPOLOGICAL
            )
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
