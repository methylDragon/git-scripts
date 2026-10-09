"""CLI subcommands for safe branch cleanup ('git cleanup')."""

# pylint: disable=too-many-arguments,too-many-positional-arguments

from typing import Annotated

import typer

from git_scripts.cli.cli_common import (
    DryRunOpt,
    PlainOpt,
    PrefixArg,
    TargetArg,
    YesOpt,
    examples,
    exit_with,
    make_app,
)
from git_scripts.cmd.cleanup import (
    execute_prune_local,
    execute_prune_remote_prefix,
)
from git_scripts.ui import UI

# --- Command Group Definitions ---

cleanup_app = make_app(
    "Safely prune obsolete local and remote branches.",
    "git cleanup branches local",
    "git cleanup branches local main --prefix feat/ --dry-run",
    "git cleanup branches remote feat/ main --dry-run",
)
cleanup_branches_app = make_app(
    "Safely prune merged or squash-merged local and remote branches.",
    "git cleanup branches local main --prefix feat/ --dry-run",
    "git cleanup branches local main --also-prune-no-upstream",
    "git cleanup branches remote feat/ main --also-prune-no-local",
)
cleanup_app.add_typer(cleanup_branches_app, name="branches")


# --- Subcommands ---


@cleanup_branches_app.command("local")
@examples(
    "git cleanup branches local",
    "git cleanup branches local main --prefix feat/ --dry-run",
    "git cleanup branches local main --also-prune-no-upstream",
)
def prune_local(
    target: TargetArg = "main",
    prefix: Annotated[
        str | None,
        typer.Option(
            "--prefix",
            "-p",
            help="Only inspect local branches starting with this prefix.",
        ),
    ] = None,
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


@cleanup_branches_app.command("remote", no_args_is_help=True)
@examples(
    "git prefix prune feat/ main --dry-run",
    "git cleanup branches remote feat/ main --also-prune-no-local",
)
def prune_remote_prefix(
    prefix: PrefixArg,
    target: TargetArg = "main",
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
