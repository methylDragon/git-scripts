"""Rich terminal UI components and abstractions."""

import sys
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property

import inflect
import questionary
from rich.console import Console
from rich.progress import Progress
from rich.prompt import Confirm


def _use_plain_fallback(*, plain: bool) -> bool:
    """Returns True when plain mode is active or stdin is not a TTY."""
    return plain or not sys.stdin.isatty()


def _ask_choice_plain(
    msg: str, choices: list[str], default: str | None = None
) -> str | None:
    """Prompts for an indexed choice using standard input."""
    print(f"{msg}")
    for i, choice in enumerate(choices):
        marker = "*" if choice == default else " "
        print(f"  {i + 1}. [{marker}] {choice}")
    default_idx = choices.index(default) + 1 if default in choices else 1
    while True:
        print(
            f"Select option (1-{len(choices)}) [Default: {default_idx}]: ",
            end="",
            flush=True,
        )
        try:
            ans = input().strip()
            idx = int(ans) - 1 if ans else -1
        except (ValueError, EOFError):
            print()
            return None
        if not ans:
            return default if default else choices[0]
        if 0 <= idx < len(choices):
            return choices[idx]


@dataclass
class UI:
    """Encapsulates UI interactions, formatting, and prompting."""

    plain: bool = False
    auto_yes: bool = False
    active_progress: Progress | None = None

    @contextmanager
    def suspend_progress(self):
        """Temporarily stops active progress bar to allow clean prompts."""
        if self.active_progress:
            self.active_progress.stop()
            try:
                yield
            finally:
                self.active_progress.start()
        else:
            yield

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

        if _use_plain_fallback(plain=self.plain):
            print(f"{msg} [Y/n] ", end="", flush=True)
            try:
                ans = input().strip().lower()
                print()  # Ensure newline for test runners
                return ans in ("", "y", "yes")
            except EOFError:
                print()  # Ensure newline for test runners
                return False

        with self.suspend_progress():
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

        if _use_plain_fallback(plain=self.plain):
            return _ask_choice_plain(msg, choices, default=default)

        with self.suspend_progress():
            return questionary.select(
                msg, choices=choices, default=default
            ).ask()

    def _ask_checkbox_plain(
        self, msg: str, choices: Sequence[str | questionary.Choice]
    ) -> list[str]:
        """Prompts for subset selection individually in plain mode."""
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

        if _use_plain_fallback(plain=self.plain):
            return self._ask_checkbox_plain(msg, choices)

        with self.suspend_progress():
            ans = questionary.checkbox(msg, choices=choices).ask()
            return ans if ans is not None else []

    def pause(self, msg: str = "Press Enter to continue...") -> None:
        """Pauses execution until the user presses Enter.

        If auto_yes is True, bypasses prompt.
        If plain mode is enabled, uses standard `input()`.
        Otherwise, uses `console.input()` to support rich formatting.
        """
        if self.auto_yes:
            return

        if _use_plain_fallback(plain=self.plain):
            try:
                input(f"{msg} ")
            except EOFError:
                pass
            return

        with self.suspend_progress():
            try:
                self.console.input(f"{msg} ")
            except EOFError:
                pass

    def print(self, *args, **kwargs) -> None:
        """Proxies to console.print."""
        self.console.print(*args, **kwargs)

    @cached_property
    def _inflect(self):
        """Cached inflect engine."""
        return inflect.engine()

    def pluralize(self, count: int, word: str) -> str:
        """Returns a formatted plural string natively handling 0 as 'no'."""
        return self._inflect.no(word, count)  # type: ignore
