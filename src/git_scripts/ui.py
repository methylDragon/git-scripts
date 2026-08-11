"""Rich terminal UI components and abstractions."""

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property

import questionary
from rich.console import Console
from rich.prompt import Confirm


@dataclass
class UI:
    """Encapsulates UI interactions, formatting, and prompting."""

    plain: bool = False
    auto_yes: bool = False

    @cached_property
    def console(self) -> Console:
        """Returns a Rich console configured for plain or interactive mode."""
        if self.plain:
            return Console(
                no_color=True, force_terminal=False, force_interactive=False
            )
        return Console()

    def confirm(self, msg: str) -> bool:
        """Prompts the user for confirmation.

        If auto_yes is True, bypasses prompt and returns True.
        If plain mode is enabled, uses standard `input()`.
        Otherwise, uses `rich.prompt.Confirm`.
        """
        if self.auto_yes:
            return True

        if self.plain:
            print(f"{msg} [Y/n] ", end="", flush=True)
            try:
                ans = input().strip().lower()
                print()  # Ensure newline for test runners
                return ans in ("", "y", "yes")
            except EOFError:
                print()  # Ensure newline for test runners
                return False

        return Confirm.ask(msg)

    def ask_choice(
        self, msg: str, choices: list[str], default: str | None = None
    ) -> str | None:
        """Prompts the user to select a single choice from a list.

        If auto_yes is True, returns the default choice.
        If plain mode is enabled, it prints options and asks for index.
        Otherwise, uses `questionary.select`.
        """
        if self.auto_yes:
            return default if default else choices[0]

        if self.plain:
            print(f"{msg}")
            for i, choice in enumerate(choices):
                marker = "*" if choice == default else " "
                print(f"  {i + 1}. [{marker}] {choice}")
            while True:
                default_idx = (
                    choices.index(default) + 1 if default in choices else 1
                )
                print(
                    f"Select option (1-{len(choices)}) "
                    f"[Default: {default_idx}]: ",
                    end="",
                    flush=True,
                )
                try:
                    ans = input().strip()
                    if not ans:
                        return default if default else choices[0]
                    idx = int(ans) - 1
                    if 0 <= idx < len(choices):
                        return choices[idx]
                except (ValueError, EOFError):
                    print()
                    return None

        return questionary.select(msg, choices=choices, default=default).ask()

    def ask_checkbox(
        self, msg: str, choices: Sequence[str | questionary.Choice]
    ) -> list[str]:
        """Prompts the user to select a subset of choices.

        If auto_yes is True, returns all choices.
        If plain mode is enabled, it asks individually.
        Otherwise, uses `questionary.checkbox`.
        """
        if self.auto_yes:
            return [
                str(c.value) if isinstance(c, questionary.Choice) else str(c)
                for c in choices
            ]

        if self.plain:
            selected = []
            print(f"{msg}")
            for choice in choices:
                val = (
                    choice.value
                    if isinstance(choice, questionary.Choice)
                    else choice
                )
                if self.confirm(f"  Process '{val}'?"):
                    selected.append(val)
            return selected

        ans = questionary.checkbox(msg, choices=choices).ask()
        return ans if ans is not None else []

    def print(self, *args, **kwargs) -> None:
        """Proxies to console.print."""
        self.console.print(*args, **kwargs)

    @contextmanager
    def spinner(self, message: str):
        """Displays a spinner while the wrapped block executes."""
        if self.plain:
            print(f"{message}...", end="", flush=True)
            yield None
            print(" Done.")
        else:
            with self.console.status(message) as status:
                yield status
