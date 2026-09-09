"""Core logic for the git-rebase-stack command."""

import pygit2

from git_scripts.cmd.rebase_prefix import execute_rebase_batch
from git_scripts.git.topology import (
    get_parent_branch,
    sort_branches_bottom_to_top,
)
from git_scripts.ui import UI


def _get_branch_commit_id(
    repo: pygit2.Repository, branch: str
) -> pygit2.Oid | None:
    try:
        return repo.revparse_single(branch).id
    except (KeyError, ValueError, pygit2.GitError):
        return None


def _walk_up_ancestors(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    branch_to_commit: dict[str, pygit2.Oid],
    stack: set[str],
) -> None:
    """Traverses ancestors up to target, adding branches to stack."""
    target_commit_id = branch_to_commit.get(target)
    curr_branch = current_branch
    while True:
        parent = get_parent_branch(repo, curr_branch, pool)
        if not parent or parent == target:
            break
        parent_cid = branch_to_commit.get(parent)
        if parent_cid == target_commit_id:
            break
        colocated_parents = {
            b for b, cid in branch_to_commit.items() if cid == parent_cid
        }
        stack.update(colocated_parents)
        curr_branch = parent


def _walk_down_descendants(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    branch_to_commit: dict[str, pygit2.Oid],
    stack: set[str],
    ui: UI,
) -> bool:
    """Traverses descendants down to tip, checking for forks."""
    curr_branch = current_branch
    while True:
        curr_cid = branch_to_commit.get(curr_branch)
        children = []
        for b in branch_to_commit:
            if b in stack or b == target:
                continue
            parent = get_parent_branch(repo, b, pool)
            if parent and branch_to_commit.get(parent) == curr_cid:
                children.append(b)

        if not children:
            break

        distinct_child_commits = {
            branch_to_commit[b] for b in children if b in branch_to_commit
        }
        if len(distinct_child_commits) > 1:
            ui.print(
                f"[red]❌  Fork detected downstream at branch '{curr_branch}'."
                "[/red]\n"
                f"    Children: {', '.join(sorted(children))}\n"
                "    Cannot determine a single linear stack to rebase.\n"
                "    Please checkout the specific tip branch you want "
                "to rebase."
            )
            return False

        stack.update(children)
        curr_branch = children[0]

    return True


def _get_linear_stack(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    ui: UI,
) -> set[str] | None:
    """Finds the full linear stack containing current_branch within pool."""
    current_commit_id = _get_branch_commit_id(repo, current_branch)
    if not current_commit_id:
        return None

    branch_to_commit = {
        b: cid
        for b in pool
        if (cid := _get_branch_commit_id(repo, b)) is not None
    }

    # Start with all branches co-located with current_branch
    stack = {
        b for b, cid in branch_to_commit.items() if cid == current_commit_id
    }

    if current_branch != target:
        _walk_up_ancestors(
            repo, current_branch, target, pool, branch_to_commit, stack
        )

    if not _walk_down_descendants(
        repo, current_branch, target, pool, branch_to_commit, stack, ui
    ):
        return None

    stack.discard(target)
    return stack


def execute_rebase_stack(
    repo_path: str = ".",
    target: str = "main",
    all_worktrees: bool = False,
    auto_delete: bool = False,
    ui: UI | None = None,
) -> bool:
    """Executes the rebase-stack command to rebase the current linear stack.

    Determines the linear branch stack containing HEAD (ancestors up to
    `target`, and descendants down to the tip) and batch-rebases them
    onto the `target` branch.

    Args:
        repo_path: Path to the git repository.
        target: The target upstream branch (defaults to 'main').
        all_worktrees: If True, detaches branches checked out in other
            worktrees before rebasing to avoid git lock errors.
        auto_delete: If True, fully merged branches are deleted.
        ui: Optional UI instance for output and confirmation prompts.

    Returns:
        True if all stack branches were processed without conflicts.
    """
    if ui is None:
        ui = UI()

    repo = pygit2.Repository(repo_path)

    if repo.head_is_detached:
        ui.print("[red]❌  Cannot rebase stack from detached HEAD.[/red]")
        return False

    current_branch = repo.head.shorthand

    if current_branch == target:
        ui.print(
            f"[yellow]Current branch is target branch '{target}'. "
            "Nothing to rebase.[/yellow]"
        )
        return True

    ui.print(f"[dim]🔍  Analyzing stack for '{current_branch}'...[/dim]")

    pool = {
        ref[len("refs/heads/") :]
        for ref in repo.references
        if ref.startswith("refs/heads/")
    }
    pool.add(target)

    stack = _get_linear_stack(repo, current_branch, target, pool, ui)
    if stack is None:
        return False

    if not stack:
        ui.print(
            f"  [yellow]No branches found in stack between '{current_branch}' "
            f"and target '{target}'.[/yellow]"
        )
        return True

    parent_map = {b: get_parent_branch(repo, b, stack) for b in stack}
    ordered_stack = sort_branches_bottom_to_top(stack, parent_map)
    ordered_stack = [b for b in ordered_stack if b != target]

    return execute_rebase_batch(
        repo_path=repo_path,
        branches=ordered_stack,
        target=target,
        all_worktrees=all_worktrees,
        auto_delete=auto_delete,
        ui=ui,
        prefix="",
    )
