"""CLI subcommands for linear branch stacks ('git stack')."""

# pylint: disable=too-many-arguments,too-many-positional-arguments

from typing import Annotated

import typer

from git_scripts.cli.cli_common import (
    PUSH_CONTEXT_SETTINGS,
    AllWorktreesOpt,
    AutoDeleteOpt,
    HiddenTargetOpt,
    PlainOpt,
    TargetArg,
    TargetOpt,
    YesOpt,
    examples,
    exit_with,
    make_app,
)
from git_scripts.cmd.evolve import execute_evolve
from git_scripts.cmd.push import execute_push_stack
from git_scripts.cmd.rebase import execute_rebase_stack
from git_scripts.ui import UI

# --- Command Group Definition ---

stack_app = make_app(
    "Rebase, push, and evolve the current linear branch stack.",
    "git stack rebase",
    "git stack rebase main --all-worktrees --auto-delete",
    "git stack push --force-with-lease",
    "git stack evolve",
)


# --- Subcommands ---


@stack_app.command("rebase")
@examples(
    "git stack rebase",
    "git stack rebase main --all-worktrees --auto-delete",
)
def rebase_stack(
    target: TargetArg = "main",
    all_worktrees: AllWorktreesOpt = False,
    auto_delete: AutoDeleteOpt = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
    target_opt: HiddenTargetOpt = None,
) -> None:
    """Rebase the current linear branch stack onto a target branch."""
    exit_with(
        execute_rebase_stack(
            repo_path=".",
            target=target_opt if target_opt is not None else target,
            all_worktrees=all_worktrees,
            auto_delete=auto_delete,
            ui=UI(plain=plain, auto_yes=yes),
        )
    )


@stack_app.command("push", context_settings=PUSH_CONTEXT_SETTINGS)
@examples(
    "git stack push",
    "git stack push --force-with-lease",
    "git stack push --target develop --force-with-lease",
)
def push_stack(
    ctx: typer.Context,
    target: TargetOpt = "main",
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Push all branches in the current linear stack to origin."""
    exit_with(
        execute_push_stack(
            repo_path=".",
            target=target,
            push_opts=ctx.args or [],
            ui=UI(plain=plain, auto_yes=yes),
        )
    )


@stack_app.command("evolve")
@examples(
    "git stack evolve",
    "git stack evolve 1a2b3c4",
)
def evolve(
    old_hash: Annotated[
        str | None,
        typer.Argument(
            help="Previous commit SHA before rewrite (auto-detected if None)."
        ),
    ] = None,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Rescue orphaned child branches after rewriting the current branch."""
    exit_with(
        execute_evolve(
            repo_path=".",
            old_hash=old_hash,
            ui=UI(plain=plain, auto_yes=yes),
        )
    )
