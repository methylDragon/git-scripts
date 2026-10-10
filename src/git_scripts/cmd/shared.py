"""Shared CLI helpers for git-scripts commands."""

from collections.abc import Callable

import pygit2
from rich.panel import Panel
from rich.progress import Progress

from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.remote import push_branches, update_target
from git_scripts.git.topology import (
    get_commit_oid,
    get_parent_branch,
    sort_branches_bottom_to_top,
)
from git_scripts.git.worktrees import WorktreeLifecycleCallbacks
from git_scripts.models import UpdateTargetResult
from git_scripts.ui import UI


def restore_branch(repo_path: str, branch: str) -> None:
    """Restores the given local branch if non-empty and still present."""
    if branch:
        try:
            run_cmd(["git", "checkout", branch], cwd=repo_path)
        except GitExecutionError:
            pass


def get_ui_worktree_callbacks(ui: UI) -> WorktreeLifecycleCallbacks:
    """Provides a set of UI-bound callbacks for worktree operations."""
    return WorktreeLifecycleCallbacks(
        on_busy=lambda wt, br: ui.print(
            f"⚠️  Warning: Worktree '{wt}' is busy. Skipping detach for '{br}'."
        ),
        on_detach=lambda wt, br: ui.print(
            f"    🍂  Detaching '{br}' in worktree '{wt}'..."
        ),
        on_detach_error=lambda wt, br, err: ui.print(
            f"⚠️  Warning: Failed to detach '{br}' in {wt}:\n{err}"
        ),
        on_reattach=lambda wt, br: ui.print(
            f"    🌱  Reattaching '{br}' in worktree '{wt}'..."
        ),
        on_reattach_error=lambda wt, br, err: ui.print(
            f"⚠️  Warning: Could not reattach '{br}' in '{wt}'.\n{err}"
        ),
        on_debug=lambda err: ui.print(f"DEBUG Error: {err}"),
    )


def ui_update_target(repo_path: str, target: str, ui: UI) -> bool:
    """Updates target branch and logs appropriate UI messages."""
    try:
        status = update_target(repo_path, target)
        if status == UpdateTargetResult.FETCHED_ONLY:
            ui.print(
                f"⚠️  Warning: Target branch '{target}' is in another "
                "worktree. Fetching its remote tracking branch instead."
            )
        elif status == UpdateTargetResult.LOCAL_ONLY:
            ui.print(
                f"⚠️  '{target}' is local-only (no upstream). Using "
                "current state."
            )
        return True
    except GitExecutionError as e:
        ui.print(f"❌  {e}")
        return False


class BranchProgressTracker:
    """Manages rich.Progress state for parallel branch operations.

    This acts as a stateful callback container for the parallel engine,
    handling progress initialization without requiring `nonlocal` vars
    or exposing rich.Progress details to the domain layer.
    """

    def __init__(self, ui: UI, description: str):
        """Initializes the tracker with a UI context and description."""
        self.ui = ui
        self.description = description
        self.progress = None
        self.task_id = None

    def __enter__(self):
        """Starts the rich.Progress context."""
        if not self.ui.plain:
            self.progress = Progress(console=self.ui.console, transient=True)
            self.progress.start()
            self.ui.active_progress = self.progress
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stops the rich.Progress context cleanly."""
        if self.progress:
            self.progress.stop()
            self.ui.active_progress = None

    def on_start(self, total_commits: int) -> None:
        """Callback to initialize the progress bar with the total ticks."""
        if self.progress:
            self.task_id = self.progress.add_task(
                f"[cyan]{self.description}...", total=total_commits
            )

    def on_progress(self, branch: str, advance_by: int) -> None:
        """Callback to advance the progress bar when a branch completes."""
        if self.progress and self.task_id is not None:
            # Strip standard remote prefix for cleaner UI display
            short_b = branch.replace("refs/remotes/origin/", "")
            self.progress.update(
                self.task_id,
                description=f"[cyan]{self.description}: {short_b}",
            )
            self.progress.advance(self.task_id, advance=advance_by)


def resolve_branches_to_push(
    branches: list[str],
    ui: UI,
    prompt_title: str | None = None,
) -> list[str]:
    """Helper to prompt the user for which branches to push."""
    if not branches:
        return []
    branches_to_push = list(branches)
    if not ui.auto_yes:
        if prompt_title is None:
            prompt_title = (
                f"Push {ui.pluralize(len(branches), 'branch')} to origin?"
            )
        action = ui.ask_choice(
            f"❓  {prompt_title}",
            choices=["Push all", "Select which to push", "Skip all"],
            default="Push all",
        )
        match action:
            case "Skip all" | None:
                return []
            case "Select which to push":
                return ui.ask_checkbox(
                    "Select branches to push:", choices=branches_to_push
                )
    return branches_to_push


def select_branches_to_delete(
    branches: list[str],
    prompt_msg: str,
    checkbox_msg: str,
    ui: UI,
    default: str = "Skip all",
) -> list[str]:
    """Prompts the user to select which branches from a bucket to delete."""
    if not branches:
        return []
    if ui.auto_yes:
        return list(branches)

    action = ui.ask_choice(
        prompt_msg,
        choices=["Skip all", "Select which to delete", "Delete all"],
        default=default,
    )
    match action:
        case "Delete all":
            return list(branches)
        case "Select which to delete":
            return ui.ask_checkbox(checkbox_msg, choices=branches)
        case _:
            return []


def prompt_and_push_updated_branches(
    branches_to_keep: set[str] | list[str],
    repo_path: str,
    ui: UI,
    *,
    panel_label: str = "Local branches updated",
    push_fn: Callable[..., bool] = push_branches,
) -> None:
    """Displays updated branches and prompts to push with force-with-lease."""
    if not branches_to_keep:
        return
    ordered_branches = (
        sorted(branches_to_keep)
        if isinstance(branches_to_keep, set)
        else list(branches_to_keep)
    )
    ui.print()
    ui.print(
        Panel(
            "\n".join(f"  - [yellow]{b}[/yellow]" for b in ordered_branches),
            title=(
                f"[bold cyan]{panel_label} "
                f"({len(ordered_branches)})[/bold cyan]"
            ),
            border_style="cyan",
            expand=False,
        )
    )
    resolved_branches = resolve_branches_to_push(
        branches=ordered_branches,
        ui=ui,
        prompt_title=(
            f"Push {ui.pluralize(len(ordered_branches), 'updated branch')} "
            "to origin?"
        ),
    )
    if resolved_branches:
        push_fn(
            branches=resolved_branches,
            options=["--force-with-lease"],
            repo_path=repo_path,
        )


def get_local_branch_pool(repo: pygit2.Repository, target: str) -> set[str]:
    """Returns all local branch names in repo plus target."""
    pool = {
        ref[len("refs/heads/") :]
        for ref in repo.references
        if ref.startswith("refs/heads/")
    }
    pool.add(target)
    return pool


def order_stack_branches(
    repo: pygit2.Repository, stack: set[str], target: str
) -> list[str]:
    """Sorts stack branches bottom-to-top, excluding target."""
    parent_map = {b: get_parent_branch(repo, b, stack) for b in stack}
    ordered = sort_branches_bottom_to_top(stack, parent_map)
    return [b for b in ordered if b != target]


def _walk_up_ancestors(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    branch_to_commit: dict[str, pygit2.Oid],
    stack: set[str],
) -> None:
    """Walks up ancestors to target, including co-located ancestor branches."""
    target_oid = branch_to_commit.get(target)
    curr = current_branch
    while True:
        parent = get_parent_branch(repo, curr, pool)
        if not parent or parent == target:
            break
        parent_oid = branch_to_commit.get(parent)
        if parent_oid is not None and parent_oid == target_oid:
            break
        if parent_oid is not None:
            stack.update(
                b for b, oid in branch_to_commit.items() if oid == parent_oid
            )
        else:
            stack.add(parent)
        curr = parent


def _find_direct_stack_children(
    repo: pygit2.Repository,
    curr: str,
    target: str,
    pool: set[str],
    branch_to_commit: dict[str, pygit2.Oid],
    stack: set[str],
) -> list[str]:
    """Finds direct children of curr in pool, matching co-located parents."""
    curr_oid = branch_to_commit.get(curr)
    children = []
    for branch in sorted(pool):
        if branch in stack or branch == target:
            continue
        parent = get_parent_branch(repo, branch, pool)
        if not parent:
            continue
        if parent == curr or (
            curr_oid is not None and branch_to_commit.get(parent) == curr_oid
        ):
            children.append(branch)
    return children


def _has_downstream_fork(
    children: list[str],
    branch_to_commit: dict[str, pygit2.Oid],
) -> bool:
    """Returns True if children point to more than one distinct commit."""
    distinct_child_commits = {
        branch_to_commit[b] for b in children if b in branch_to_commit
    }
    return len(distinct_child_commits) > 1 or (
        not distinct_child_commits and len(children) > 1
    )


def resolve_linear_stack(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    ui: UI,
    *,
    action_verb: str,
) -> set[str] | None:
    """Discovers the linear stack for current_branch or prints fork error."""
    branch_to_commit = {
        b: oid for b in pool if (oid := get_commit_oid(repo, b)) is not None
    }
    current_oid = branch_to_commit.get(current_branch)
    target_oid = branch_to_commit.get(target)

    if current_oid is not None and current_oid != target_oid:
        stack = {
            b
            for b, oid in branch_to_commit.items()
            if oid == current_oid and b != target
        }
    else:
        stack = {current_branch}

    if current_branch != target:
        _walk_up_ancestors(
            repo, current_branch, target, pool, branch_to_commit, stack
        )

    curr = current_branch
    while True:
        children = _find_direct_stack_children(
            repo, curr, target, pool, branch_to_commit, stack
        )
        if not children:
            break

        if _has_downstream_fork(children, branch_to_commit):
            ui.print(
                f"[red]❌  Fork detected downstream at branch '{curr}'."
                "[/red]\n"
                f"    Children: {', '.join(children)}\n"
                "    Cannot determine a single linear stack to "
                f"{action_verb}.\n"
                "    Please checkout the specific tip branch you want "
                f"to {action_verb}."
            )
            return None

        stack.update(children)
        curr = children[0]

    stack.discard(target)
    return stack
