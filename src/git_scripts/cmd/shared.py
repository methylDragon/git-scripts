"""Shared CLI helpers for git-scripts commands."""

from rich.progress import Progress

from git_scripts.git.core import GitExecutionError
from git_scripts.git.remote import update_target
from git_scripts.git.worktrees import WorktreeLifecycleCallbacks
from git_scripts.models import UpdateTargetResult
from git_scripts.ui import UI


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
            prompt_title = f"Push {len(branches)} branches to origin?"
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
