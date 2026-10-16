"""Root CLI application and subcommand group wiring."""

from typing import Annotated

import typer

from git_scripts.cli.batch_commands import batch_app
from git_scripts.cli.cli_common import (
    PlainOpt,
    YesOpt,
    examples,
    exit_with,
    make_app,
)
from git_scripts.cli.gh_commands import gh_app
from git_scripts.cli.gk_commands import gk_app
from git_scripts.cmd.evolve import execute_evolve
from git_scripts.ui import UI

# --- Root Application ---

app = make_app(
    "Git workflow utilities for linear stacks, prefixed branch trees, "
    "safe branch cleanup, GitHub stacked PR alignment, and GitKraken "
    "optimization.",
    "git batch rebase main --all-worktrees",
    "git batch rebase main --prefix feat/ --all-worktrees",
    "git batch push --prefix feat/ --force-with-lease",
    "git batch prune local main --prefix feat/ --dry-run",
    "git evolve",
    "git gh align --prefix feat/ --all",
    "git gk install --close-gitkraken",
)

# --- Subcommand Group Registration ---

app.add_typer(batch_app, name="batch")
app.add_typer(gh_app, name="gh")
app.add_typer(gk_app, name="gk")


# --- Root Commands ---


@app.command("evolve")
@examples(
    "git evolve",
    "git evolve 1a2b3c4",
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


# --- Entrypoint ---


def main() -> None:
    """CLI entrypoint."""
    app(prog_name="git")


__all__ = ["app", "evolve", "main"]
