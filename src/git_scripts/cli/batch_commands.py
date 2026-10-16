"""CLI subcommands for action-first multi-branch workflows ('git batch')."""

# pylint: disable=too-many-arguments,too-many-positional-arguments

from typing import Annotated

import typer

from git_scripts.cli.cli_common import (
    PUSH_CONTEXT_SETTINGS,
    AllWorktreesOpt,
    AutoDeleteOpt,
    CurrentOpt,
    DryRunOpt,
    PlainOpt,
    PrefixOpt,
    TargetArg,
    TargetOpt,
    YesOpt,
    examples,
    exit_with,
    make_app,
    validate_scope_options,
)
from git_scripts.cmd.cleanup import (
    execute_prune_local,
    execute_prune_remote_prefix,
)
from git_scripts.cmd.push import execute_push_prefix, execute_push_stack
from git_scripts.cmd.rebase import execute_rebase_prefix, execute_rebase_stack
from git_scripts.ui import UI

# --- Command Group Definitions ---

batch_app = make_app(
    "Rebase, push, and prune linear stacks or branch trees matching a prefix.",
    "git batch rebase main --all-worktrees",
    "git batch rebase main --prefix feat/ --all-worktrees",
    "git batch push --prefix feat/ --force-with-lease",
    "git batch prune local main --prefix feat/ --dry-run",
    "git batch prune remote main --prefix feat/ --dry-run",
)
batch_prune_app = make_app(
    "Safely prune merged or squash-merged local and remote branches.",
    "git batch prune local main --prefix feat/ --dry-run",
    "git batch prune local main --also-prune-no-upstream",
    "git batch prune remote main --prefix feat/ --dry-run",
)
batch_app.add_typer(batch_prune_app, name="prune")


# --- Subcommands ---


@batch_app.command("rebase")
@examples(
    "git batch rebase",
    "git batch rebase main --current --all-worktrees",
    "git batch rebase main --prefix feat/ --all-worktrees --auto-delete",
    "git batch rebase main -p feat/ --dry-run",
)
def batch_rebase(
    target: TargetArg = "main",
    current: CurrentOpt = False,
    prefix: PrefixOpt = None,
    all_worktrees: AllWorktreesOpt = False,
    auto_delete: AutoDeleteOpt = False,
    dry_run: DryRunOpt = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Rebase the current stack (default) or --prefix branches onto target."""
    validate_scope_options(
        current=current, prefix=prefix, cmd_label="git batch rebase"
    )
    ui = UI(plain=plain, auto_yes=yes)
    if prefix is not None:
        exit_with(
            execute_rebase_prefix(
                repo_path=".",
                prefix=prefix,
                target=target,
                all_worktrees=all_worktrees,
                auto_delete=auto_delete,
                dry_run=dry_run,
                ui=ui,
            )
        )
    exit_with(
        execute_rebase_stack(
            repo_path=".",
            target=target,
            all_worktrees=all_worktrees,
            auto_delete=auto_delete,
            dry_run=dry_run,
            ui=ui,
        )
    )


@batch_app.command("push", context_settings=PUSH_CONTEXT_SETTINGS)
@examples(
    "git batch push",
    "git batch push --current --force-with-lease",
    "git batch push --prefix feat/ --force-with-lease",
    "git batch push -p feat/ --dry-run",
)
def batch_push(
    ctx: typer.Context,
    current: CurrentOpt = False,
    prefix: PrefixOpt = None,
    target: TargetOpt = "main",
    dry_run: DryRunOpt = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Push the current stack (default) or --prefix branches to origin."""
    validate_scope_options(
        current=current, prefix=prefix, cmd_label="git batch push"
    )
    push_opts = list(ctx.args)
    if dry_run and "--dry-run" not in push_opts and "-n" not in push_opts:
        push_opts.append("--dry-run")
    ui = UI(plain=plain, auto_yes=yes)
    if prefix is not None:
        exit_with(
            execute_push_prefix(
                repo_path=".",
                prefix=prefix,
                push_opts=push_opts,
                ui=ui,
            )
        )
    exit_with(
        execute_push_stack(
            repo_path=".",
            target=target,
            push_opts=push_opts,
            ui=ui,
        )
    )


@batch_prune_app.command("local")
@examples(
    "git batch prune local",
    "git batch prune local main --prefix feat/ --dry-run",
    "git batch prune local main --also-prune-no-upstream",
)
def batch_prune_local(
    target: TargetArg = "main",
    prefix: PrefixOpt = None,
    dry_run: DryRunOpt = False,
    also_prune_no_upstream: Annotated[
        bool,
        typer.Option(
            "--also-prune-no-upstream",
            help="Also inspect local branches without an upstream branch.",
        ),
    ] = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Prune local branches whose upstream tracking branches are gone."""
    exit_with(
        execute_prune_local(
            repo_path=".",
            dry_run=dry_run,
            also_prune_no_upstream=also_prune_no_upstream,
            target=target,
            prefix=prefix,
            ui=UI(plain=plain, auto_yes=yes),
        )
    )


@batch_prune_app.command("remote")
@examples(
    "git batch prune remote -p feat/ --dry-run",
    "git batch prune remote main --prefix feat/ --also-prune-no-local",
)
def batch_prune_remote(
    target: TargetArg = "main",
    prefix: PrefixOpt = None,
    dry_run: DryRunOpt = False,
    also_prune_no_local: Annotated[
        bool,
        typer.Option(
            "--also-prune-no-local",
            help="Also inspect remote branches with no matching local branch.",
        ),
    ] = False,
    plain: PlainOpt = False,
    yes: YesOpt = False,
) -> None:
    """Prune remote origin/<prefix>* branches merged into a target branch."""
    if prefix is None:
        raise typer.BadParameter(
            "Missing branch prefix. Pass --prefix (-p) <pfx>, e.g. "
            "'git batch prune remote -p feat/ --dry-run'."
        )
    exit_with(
        execute_prune_remote_prefix(
            repo_path=".",
            prefix=prefix,
            target=target,
            dry_run=dry_run,
            also_prune_no_local=also_prune_no_local,
            ui=UI(plain=plain, auto_yes=yes),
        )
    )
