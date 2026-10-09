"""CLI subcommands for GitKraken Desktop optimization ('git gk')."""

# pylint: disable=too-many-arguments,too-many-positional-arguments

from pathlib import Path
from typing import Annotated

import typer

from git_scripts.cli.cli_common import (
    CloseGkOpt,
    PlainOpt,
    RepoPathArg,
    YesOpt,
    examples,
    exit_with,
    make_app,
)
from git_scripts.cmd.gk_optimize import (
    GkExpectMode,
    execute_gk_install,
    execute_gk_uninstall,
    execute_gk_verify,
    execute_watch_daemon,
)
from git_scripts.ui import UI

# --- Command Group Definition ---

gk_app = make_app(
    "Install, verify, and uninstall GitKraken worktree/tag optimizations.",
    "git gk install --close-gitkraken",
    "git gk verify",
    "git gk uninstall --close-gitkraken",
)


# --- Subcommands ---


@gk_app.command("install")
@examples(
    "git gk install --close-gitkraken",
    "git gk install /path/to/repo --keep-recent-tags 10",
)
def gk_install(
    repo_path: RepoPathArg = ".",
    config: Annotated[
        Path | None,
        typer.Option(
            "--config", help="Path to custom YAML configuration file."
        ),
    ] = None,
    keep_recent_tags: Annotated[
        int | None,
        typer.Option(
            "--keep-recent-tags",
            help="Override count of recent tags kept per pattern.",
        ),
    ] = None,
    close_gitkraken: CloseGkOpt = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Install GitKraken worktree switching and auto-refresh optimizations."""
    result = execute_gk_install(
        repo_path=repo_path,
        ui=UI(plain=plain, auto_yes=yes),
        config_path=config,
        keep_recent_override=keep_recent_tags,
        close_gitkraken=close_gitkraken,
    )
    exit_with(result.success)


@gk_app.command("verify")
@examples(
    "git gk verify",
    "git gk verify --expect uninstalled",
)
def gk_verify(
    repo_path: RepoPathArg = ".",
    expect: Annotated[
        GkExpectMode,
        typer.Option(
            "--expect",
            help="Expected optimization state ('installed' or 'uninstalled').",
        ),
    ] = GkExpectMode.INSTALLED,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Verify whether GitKraken optimizations are active or reverted."""
    result = execute_gk_verify(
        repo_path=repo_path,
        ui=UI(plain=plain, auto_yes=yes),
        expect=expect,
    )
    exit_with(result.passed)


@gk_app.command("uninstall")
@examples("git gk uninstall --close-gitkraken")
def gk_uninstall(
    repo_path: RepoPathArg = ".",
    close_gitkraken: CloseGkOpt = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Revert GitKraken Desktop optimizations safely via Compare-And-Swap."""
    result = execute_gk_uninstall(
        repo_path=repo_path,
        ui=UI(plain=plain, auto_yes=yes),
        close_gitkraken=close_gitkraken,
    )
    exit_with(result.success)


@gk_app.command("watch-daemon", hidden=True)
def gk_watch_daemon(
    common_git_dir: Annotated[
        Path, typer.Argument(help="Path to shared .git common directory.")
    ],
    gk_pid: Annotated[
        int | None,
        typer.Option("--gk-pid", help="GitKraken PID for daemon auto-exit."),
    ] = None,
) -> None:
    """Run background watcher for worktree refresh and tag windows."""
    exit_with(
        execute_watch_daemon(
            common_git_dir=common_git_dir.resolve(),
            gk_pid=gk_pid,
        )
    )
