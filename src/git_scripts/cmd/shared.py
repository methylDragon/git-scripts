"""Shared CLI helpers for git-scripts commands."""

from git_scripts.ui import UI


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
