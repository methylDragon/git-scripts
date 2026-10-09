"""Root CLI application, subcommand group wiring, and legacy aliases."""

from git_scripts.cli.cleanup_commands import (
    cleanup_app,
    prune_local,
    prune_remote_prefix,
)
from git_scripts.cli.cli_common import PUSH_CONTEXT_SETTINGS, make_app
from git_scripts.cli.gh_commands import (
    gh_align_pr_bases_and_sync_stacks,
    gh_app,
)
from git_scripts.cli.gk_commands import gk_app
from git_scripts.cli.prefix_commands import (
    prefix_app,
    push_prefix,
    rebase_prefix,
)
from git_scripts.cli.stack_commands import (
    evolve,
    push_stack,
    rebase_stack,
    stack_app,
)

# --- Root Application ---

app = make_app(
    "Git workflow utilities for linear stacks, prefixed branch trees, "
    "safe branch cleanup, GitHub stacked PR alignment, and GitKraken "
    "optimization.",
    "git stack rebase main --all-worktrees",
    "git prefix rebase feat/ main --all-worktrees",
    "git cleanup branches local main --prefix feat/ --dry-run",
    "git gh align feat/ main --all",
    "git gk install --close-gitkraken",
)

# --- Subcommand Group Registration ---

app.add_typer(stack_app, name="stack")
app.add_typer(prefix_app, name="prefix")
app.add_typer(cleanup_app, name="cleanup")
app.add_typer(gh_app, name="gh")
app.add_typer(gk_app, name="gk")
app.add_typer(gk_app, name="gk-optimize", hidden=True)

# --- Root and Backward-Compatible Command Aliases ---

app.command("evolve")(evolve)
app.command("rebase-stack", hidden=True)(rebase_stack)
app.command("rebase-prefix", hidden=True)(rebase_prefix)
app.command("push-stack", hidden=True, context_settings=PUSH_CONTEXT_SETTINGS)(
    push_stack
)
app.command(
    "push-prefix", hidden=True, context_settings=PUSH_CONTEXT_SETTINGS
)(push_prefix)
app.command("prune-local", hidden=True)(prune_local)
app.command("prune-remote-prefix", hidden=True)(prune_remote_prefix)
app.command("gh-align-pr-bases-and-sync-stacks", hidden=True)(
    gh_align_pr_bases_and_sync_stacks
)


# --- Entrypoint ---


def main() -> None:
    """CLI entrypoint."""
    app(prog_name="git")


__all__ = ["app", "main"]
