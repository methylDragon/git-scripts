"""Command line interface presentation layer."""

from typing import Annotated

import typer

from git_scripts.cmd.evolve import execute_evolve
from git_scripts.cmd.prune_local import execute_prune_local
from git_scripts.cmd.prune_remote import execute_prune_remote
from git_scripts.cmd.push_prefix import execute_push_prefix
from git_scripts.cmd.rebase_prefix import execute_rebase_prefix
from git_scripts.ui import UI

app = typer.Typer(help="Git Stack Utilities", add_completion=False)


@app.command("rebase-prefix")
def rebase_prefix(
    prefix: Annotated[str, typer.Argument(help="Branch prefix to search for")],
    target: Annotated[str, typer.Argument(help="Target branch")] = "main",
    all_worktrees: Annotated[
        bool, typer.Option("--all-worktrees", help="Cross-worktree rebase")
    ] = False,
    auto_delete: Annotated[
        bool, typer.Option("--auto-delete", help="Auto delete merged branches")
    ] = False,
    obsolete_search_depth: Annotated[
        int,
        typer.Option(
            "--obsolete-search-depth",
            help=(
                "Commits to traverse back on the target branch to "
                "detect squash merges or cherry-picks. Increase this "
                "if your target branch moves very quickly."
            ),
        ),
    ] = 100,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help="Disable rich formatting and use plain text prompts",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "-y", "--yes", help="Automatically bypass confirmation prompts"
        ),
    ] = False,
):
    """Batch updates stacks by rebasing them onto a target branch."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_rebase_prefix(
        repo_path=".",
        prefix=prefix,
        target=target,
        all_worktrees=all_worktrees,
        auto_delete=auto_delete,
        search_depth=obsolete_search_depth,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


@app.command(
    "push-prefix",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def push_prefix(
    ctx: typer.Context,
    prefix: Annotated[str, typer.Argument(help="Branch prefix to search for")],
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help="Disable rich formatting and use plain text prompts",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "-y", "--yes", help="Automatically bypass confirmation prompts"
        ),
    ] = False,
    all_worktrees: Annotated[
        bool,
        typer.Option(
            "--all-worktrees",
            help="Obsolete flag for backwards compatibility",
            hidden=True,
        ),
    ] = False,
):
    """Batch push stacks to the remote."""
    ui = UI(plain=plain, auto_yes=yes)

    push_opts = [arg for arg in ctx.args if arg != "--all-worktrees"]

    success = execute_push_prefix(
        repo_path=".",
        prefix=prefix,
        push_opts=push_opts or [],
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


@app.command("evolve")
def evolve(
    old_hash: Annotated[
        str, typer.Argument(help="Old base commit sha")
    ] = None,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help="Disable rich formatting and use plain text prompts",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "-y", "--yes", help="Automatically bypass confirmation prompts"
        ),
    ] = False,
):
    """Rescues orphaned children after a stack base is rewritten."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_evolve(
        repo_path=".",
        old_hash=old_hash,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


@app.command("prune-local")
def prune_local(
    dry_run: Annotated[
        bool,
        typer.Option("-n", "--dry-run", help="Run without making changes"),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help="Disable rich formatting and use plain text prompts",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "-y", "--yes", help="Automatically bypass confirmation prompts"
        ),
    ] = False,
):
    """Prunes orphaned local tracking branches."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_prune_local(repo_path=".", dry_run=dry_run, ui=ui)
    raise typer.Exit(code=0 if success else 1)


@app.command("prune-remote")
def prune_remote(
    prefix: Annotated[str, typer.Argument(help="Prefix to match")],
    target: Annotated[str, typer.Argument(help="Target branch")] = "main",
    dry_run: Annotated[
        bool,
        typer.Option("-n", "--dry-run", help="Run without making changes"),
    ] = False,
    obsolete_search_depth: Annotated[
        int,
        typer.Option(
            "--obsolete-search-depth",
            help=(
                "Commits to traverse back on the target branch to "
                "detect squash merges or cherry-picks to find obsolete "
                "stacks. Increase this if your target branch moves quickly."
            ),
        ),
    ] = 100,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help="Disable rich formatting and use plain text prompts",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "-y", "--yes", help="Automatically bypass confirmation prompts"
        ),
    ] = False,
):
    """Prunes obsolete remote branches."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_prune_remote(
        repo_path=".",
        prefix=prefix,
        target=target,
        dry_run=dry_run,
        search_depth=obsolete_search_depth,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


def main():
    """Main entrypoint for git-scripts."""
    app()


if __name__ == "__main__":
    main()
