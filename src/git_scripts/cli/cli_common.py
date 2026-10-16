"""Shared Typer factories, help formatters, and Annotated CLI option types."""

from collections.abc import Callable
from typing import Annotated, Any, Final, NoReturn, TypeVar

import typer

_F = TypeVar("_F", bound=Callable[..., Any])

# --- Context Settings ---

HELP_CONTEXT_SETTINGS: Final[dict[str, Any]] = {
    "help_option_names": ["-h", "--help"]
}
PUSH_CONTEXT_SETTINGS: Final[dict[str, Any]] = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
    "help_option_names": ["-h", "--help"],
}

# --- Shared Argument and Option Types ---

PrefixOpt = Annotated[
    str | None,
    typer.Option(
        "--prefix",
        "-p",
        help="Branch name prefix to match (e.g. 'feat/' or 'stack/').",
    ),
]
CurrentOpt = Annotated[
    bool,
    typer.Option(
        "--current",
        "-c",
        help="Operate only on the checked-out linear branch stack.",
    ),
]
TargetArg = Annotated[
    str,
    typer.Argument(help="Target trunk branch (default: 'main')."),
]
TargetOpt = Annotated[
    str,
    typer.Option("--target", help="Target trunk branch (default: 'main')."),
]
AllWorktreesOpt = Annotated[
    bool,
    typer.Option(
        "--all-worktrees",
        help="Temporarily detach/reattach branches in other worktrees.",
    ),
]
AutoDeleteOpt = Annotated[
    bool,
    typer.Option(
        "--auto-delete",
        help="Automatically delete branches that become empty/merged.",
    ),
]
DryRunOpt = Annotated[
    bool,
    typer.Option(
        "-n",
        "--dry-run",
        help="Preview planned branch changes without mutating Git state.",
    ),
]
RepoPathArg = Annotated[
    str,
    typer.Argument(help="Target repository or worktree path (default: '.')."),
]
CloseGkOpt = Annotated[
    bool,
    typer.Option(
        "--close-gitkraken",
        help="Close running GitKraken instances before applying changes.",
    ),
]
PlainOpt = Annotated[
    bool,
    typer.Option(
        "--plain",
        help="Disable rich formatting and use plain text prompts.",
    ),
]
YesOpt = Annotated[
    bool,
    typer.Option(
        "-y",
        "--yes",
        help="Automatically confirm prompts without interactive input.",
    ),
]


# --- App Factories and Command Helpers ---


def format_help(summary: str, *examples_list: str) -> str:
    """Format a help description with an optional multi-line Examples block."""
    if not examples_list:
        return summary
    body = "\n".join(f"  {ex}" for ex in examples_list)
    return f"{summary}\n\n\b\nExamples:\n{body}"


def make_app(summary: str, *examples_list: str) -> typer.Typer:
    """Create a Typer command group with a summary and examples."""
    return typer.Typer(
        help=format_help(summary, *examples_list),
        no_args_is_help=True,
        add_completion=False,
        context_settings=HELP_CONTEXT_SETTINGS,
    )


def examples(*examples_list: str) -> Callable[[_F], _F]:
    """Attach a formatted Examples block to a command function's docstring."""

    def decorator(fn: _F) -> _F:
        fn.__doc__ = format_help((fn.__doc__ or "").strip(), *examples_list)
        return fn

    return decorator


def exit_with(ok: bool) -> NoReturn:
    """Raise typer.Exit with 0 on success and 1 on failure."""
    raise typer.Exit(code=0 if ok else 1)


def validate_scope_options(
    *, current: bool, prefix: str | None, cmd_label: str
) -> None:
    """Rejects mutually exclusive --current and --prefix options."""
    if current and prefix is not None:
        raise typer.BadParameter(
            "Cannot combine --current (-c) and --prefix (-p). "
            f"Run '{cmd_label} --current' for the checked-out stack or "
            f"'{cmd_label} --prefix <pfx>' for matching branches."
        )
