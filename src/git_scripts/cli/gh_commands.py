"""CLI subcommands for GitHub stacked PR workflows ('git gh')."""

# pylint: disable=too-many-arguments,too-many-positional-arguments

from typing import Annotated

import typer

from git_scripts.cli.cli_common import (
    OptionalPrefixArg,
    PlainOpt,
    TargetArg,
    YesOpt,
    examples,
    exit_with,
    make_app,
)
from git_scripts.cmd.gh.pr_aligner import (
    execute_align_pr_bases_and_sync_stacks,
)
from git_scripts.ui import UI

# --- Command Group Definition ---

gh_app = make_app(
    "Align GitHub PR bases, create missing PRs, and sync gh-stack tables.",
    "git gh align",
    "git gh align feat/ main --all",
    "git gh align feat/ main -i --create-missing",
)


# --- Subcommands ---


@gh_app.command("align")
@examples(
    "git gh align",
    "git gh align feat/ main --all",
    "git gh align feat/ main -i --create-missing",
)
def gh_align_pr_bases_and_sync_stacks(
    prefix: OptionalPrefixArg = None,
    target: TargetArg = "main",
    current: Annotated[
        bool,
        typer.Option(
            "--current", help="Only align the checked-out linear stack."
        ),
    ] = False,
    all_matching: Annotated[
        bool,
        typer.Option(
            "--all", help="Align all stacks matching <prefix> without prompt."
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Interactively select stacks or branches to align.",
        ),
    ] = False,
    create_missing: Annotated[
        bool,
        typer.Option(
            "--create-missing",
            help="Create missing GitHub PRs using the repo PR template.",
        ),
    ] = False,
    remote: Annotated[
        str | None,
        typer.Option(
            "--remote",
            "-r",
            help="Git remote to push and align against.",
        ),
    ] = None,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Align GitHub PR bases, create missing PRs, and sync gh-stack tables."""
    exit_with(
        execute_align_pr_bases_and_sync_stacks(
            repo_path=".",
            prefix=prefix,
            target=target,
            current_stack_only=current,
            all_matching=all_matching,
            create_missing=create_missing,
            interactive=interactive,
            remote=remote,
            ui=UI(plain=plain, auto_yes=yes),
        )
    )
