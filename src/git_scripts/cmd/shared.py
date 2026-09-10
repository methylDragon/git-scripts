"""Shared CLI helpers for git-scripts commands."""

from rich.progress import Progress

from git_scripts.ui import UI


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
