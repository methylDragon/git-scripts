"""CLI subcommands for prefixed branch trees ('git prefix')."""

# pylint: disable=too-many-arguments,too-many-positional-arguments

import typer

from git_scripts.cli.cleanup_commands import prune_remote_prefix
from git_scripts.cli.cli_common import (
    PUSH_CONTEXT_SETTINGS,
    AllWorktreesOpt,
    AutoDeleteOpt,
    HiddenAllWorktreesOpt,
    PlainOpt,
    PrefixArg,
    TargetArg,
    YesOpt,
    examples,
    exit_with,
    make_app,
)
from git_scripts.cmd.push import execute_push_prefix
from git_scripts.cmd.rebase import execute_rebase_prefix
from git_scripts.ui import UI

# --- Command Group Definition ---

prefix_app = make_app(
    "Batch rebase, push, and prune branch trees matching a name prefix.",
    "git prefix rebase <prefix> \\[target] --all-worktrees",
    "git prefix push feat/ --force-with-lease",
    "git prefix prune feat/ main --dry-run",
)


# --- Subcommands ---


@prefix_app.command("rebase", no_args_is_help=True)
@examples(
    "git prefix rebase feat/",
    "git prefix rebase feat/ develop --all-worktrees --auto-delete",
)
def rebase_prefix(
    prefix: PrefixArg,
    target: TargetArg = "main",
    all_worktrees: AllWorktreesOpt = False,
    auto_delete: AutoDeleteOpt = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Batch-rebase all local branches matching <prefix> onto a target."""
    exit_with(
        execute_rebase_prefix(
            repo_path=".",
            prefix=prefix,
            target=target,
            all_worktrees=all_worktrees,
            auto_delete=auto_delete,
            ui=UI(plain=plain, auto_yes=yes),
        )
    )


@prefix_app.command(
    "push", no_args_is_help=True, context_settings=PUSH_CONTEXT_SETTINGS
)
@examples(
    "git prefix push feat/",
    "git prefix push feat/ --force-with-lease",
)
def push_prefix(
    ctx: typer.Context,
    prefix: PrefixArg,
    plain: PlainOpt = False,
    yes: YesOpt = False,
    all_worktrees: HiddenAllWorktreesOpt = False,
) -> None:
    """Batch-push all local branches matching <prefix> to origin."""
    del all_worktrees
    push_opts = [arg for arg in ctx.args if arg != "--all-worktrees"]
    exit_with(
        execute_push_prefix(
            repo_path=".",
            prefix=prefix,
            push_opts=push_opts or [],
            ui=UI(plain=plain, auto_yes=yes),
        )
    )


prefix_app.command("prune", no_args_is_help=True)(prune_remote_prefix)
