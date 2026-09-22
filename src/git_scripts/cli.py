"""Command-line interface definition and routing."""

# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument

from pathlib import Path
from typing import Annotated

import typer

from git_scripts.cmd.evolve import execute_evolve
from git_scripts.cmd.gh_align_pr_bases_and_sync_stacks import (
    execute_align_pr_bases_and_sync_stacks,
)
from git_scripts.cmd.gk_optimize import (
    execute_gk_install,
    execute_gk_uninstall,
    execute_gk_verify,
)
from git_scripts.cmd.prune_local import execute_prune_local
from git_scripts.cmd.prune_remote_prefix import execute_prune_remote_prefix
from git_scripts.cmd.push_prefix import execute_push_prefix
from git_scripts.cmd.push_stack import execute_push_stack
from git_scripts.cmd.rebase_prefix import execute_rebase_prefix
from git_scripts.cmd.rebase_stack import execute_rebase_stack
from git_scripts.gk.optimize.models import GkExpectMode
from git_scripts.gk.optimize.watcher import execute_watch_daemon
from git_scripts.ui import UI

app = typer.Typer(help="Git Stack Utilities", add_completion=False)
gk_app = typer.Typer(
    help="Optimize GitKraken Desktop worktree switching and auto-refresh",
    add_completion=False,
)
app.add_typer(gk_app, name="gk-optimize")


@app.command("rebase-stack")
def rebase_stack(
    target: Annotated[
        str,
        typer.Argument(
            help="Target branch to rebase onto (defaults to 'main')",
        ),
    ] = "main",
    all_worktrees: Annotated[
        bool, typer.Option("--all-worktrees", help="Cross-worktree rebase")
    ] = False,
    auto_delete: Annotated[
        bool, typer.Option("--auto-delete", help="Auto delete merged branches")
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
    target_opt: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="Target branch (alternative flag)",
            hidden=True,
        ),
    ] = None,
):
    """Batch rebases the current branch stack onto a target branch."""
    ui = UI(plain=plain, auto_yes=yes)

    effective_target = target_opt if target_opt is not None else target

    success = execute_rebase_stack(
        repo_path=".",
        target=effective_target,
        all_worktrees=all_worktrees,
        auto_delete=auto_delete,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
):
    """Batch rebases stacked branches onto a target branch."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_rebase_prefix(
        repo_path=".",
        prefix=prefix,
        target=target,
        all_worktrees=all_worktrees,
        auto_delete=auto_delete,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


@app.command(
    "push-stack",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def push_stack(
    ctx: typer.Context,
    target: Annotated[
        str,
        typer.Option("--target", help="Target branch"),
    ] = "main",
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
):
    """Batch pushes the current stacked branches to the remote."""
    ui = UI(plain=plain, auto_yes=yes)

    # Allow all extra args to be passed to git push except our own
    # internal options. Just be careful not to consume git push flags as
    # our own options.
    push_opts = ctx.args

    success = execute_push_stack(
        repo_path=".",
        target=target,
        push_opts=push_opts or [],
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
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
    """Batch pushes stacked branches to the remote."""
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
        str | None,
        typer.Argument(help="Old base commit sha"),
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
):
    """Rescues orphaned child branches after their base commit is rewritten."""
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
):
    """Prunes local branches whose remote tracking branches are gone."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_prune_local(repo_path=".", dry_run=dry_run, ui=ui)
    raise typer.Exit(code=0 if success else 1)


@app.command("prune-remote-prefix")
def prune_remote_prefix(
    prefix: Annotated[str, typer.Argument(help="Prefix to match")],
    target: Annotated[str, typer.Argument(help="Target branch")] = "main",
    dry_run: Annotated[
        bool,
        typer.Option("-n", "--dry-run", help="Run without making changes"),
    ] = False,
    also_prune_no_local: Annotated[
        bool,
        typer.Option(
            "--also-prune-no-local",
            help="Also prune remotes lacking a matching local branch",
        ),
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
):
    """Prunes remote branches that have been fully merged into the target."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_prune_remote_prefix(
        repo_path=".",
        prefix=prefix,
        target=target,
        dry_run=dry_run,
        also_prune_no_local=also_prune_no_local,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


@app.command("gh-align-pr-bases-and-sync-stacks")
def gh_align_pr_bases_and_sync_stacks(
    prefix: Annotated[
        str | None,
        typer.Argument(
            help="Prefix to match (optional, defaults to current stack)",
        ),
    ] = None,
    target: Annotated[str, typer.Argument(help="Target branch")] = "main",
    current: Annotated[
        bool,
        typer.Option("--current", help="Only align the current linear stack"),
    ] = False,
    all_matching: Annotated[
        bool,
        typer.Option("--all", help="Align all branches matching the prefix"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Interactively select which stacks/branches to align",
        ),
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
            "-y",
            "--yes",
            help="Automatically bypass confirmation prompts",
        ),
    ] = False,
):
    """Aligns GitHub PR bases with local topology."""
    ui = UI(plain=plain, auto_yes=yes)

    success = execute_align_pr_bases_and_sync_stacks(
        repo_path=".",
        prefix=prefix,
        target=target,
        current_stack_only=current,
        all_matching=all_matching,
        interactive=interactive,
        ui=ui,
    )
    raise typer.Exit(code=0 if success else 1)


@gk_app.command("install")
def gk_install(
    repo_path: Annotated[
        str, typer.Argument(help="Path to target repository or worktree")
    ] = ".",
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to custom YAML config file"),
    ] = None,
    keep_recent_tags: Annotated[
        int | None,
        typer.Option(
            "--keep-recent-tags",
            help="Override recent tag count kept per configured pattern",
        ),
    ] = None,
    close_gitkraken: Annotated[
        bool,
        typer.Option(
            "--close-gitkraken",
            help="Close running GitKraken instances before applying settings",
        ),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Disable rich formatting"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("-y", "--yes", help="Bypass confirmation prompts"),
    ] = False,
):
    """Installs GitKraken worktree switching and auto-refresh optimizations."""
    ui = UI(plain=plain, auto_yes=yes)
    result = execute_gk_install(
        repo_path=repo_path,
        ui=ui,
        config_path=config,
        keep_recent_override=keep_recent_tags,
        close_gitkraken=close_gitkraken,
    )
    raise typer.Exit(code=0 if result.success else 1)


@gk_app.command("verify")
def gk_verify(
    repo_path: Annotated[
        str, typer.Argument(help="Path to target repository or worktree")
    ] = ".",
    expect: Annotated[
        GkExpectMode,
        typer.Option(
            "--expect",
            help="Expected state (installed/uninstalled)",
        ),
    ] = GkExpectMode.INSTALLED,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Disable rich formatting"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("-y", "--yes", help="Bypass confirmation prompts"),
    ] = False,
):
    """Verifies whether GitKraken optimizations are active or reverted."""
    ui = UI(plain=plain, auto_yes=yes)
    result = execute_gk_verify(repo_path=repo_path, ui=ui, expect=expect)
    raise typer.Exit(code=0 if result.passed else 1)


@gk_app.command("uninstall")
def gk_uninstall(
    repo_path: Annotated[
        str, typer.Argument(help="Path to target repository or worktree")
    ] = ".",
    close_gitkraken: Annotated[
        bool,
        typer.Option(
            "--close-gitkraken",
            help="Close running GitKraken instances before reverting settings",
        ),
    ] = False,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Disable rich formatting"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("-y", "--yes", help="Bypass confirmation prompts"),
    ] = False,
):
    """Reverts GitKraken optimizations safely via Compare-And-Swap."""
    ui = UI(plain=plain, auto_yes=yes)
    result = execute_gk_uninstall(
        repo_path=repo_path,
        ui=ui,
        close_gitkraken=close_gitkraken,
    )
    raise typer.Exit(code=0 if result.success else 1)


@gk_app.command("watch-daemon", hidden=True)
def gk_watch_daemon(
    common_git_dir: Annotated[
        Path, typer.Argument(help="Path to shared .git common directory")
    ],
    gk_pid: Annotated[
        int | None,
        typer.Option("--gk-pid", help="GitKraken PID for daemon auto-exit"),
    ] = None,
):
    """Runs singleton background watcher for worktree refresh & tag windows."""
    common_resolved = common_git_dir.resolve()
    ok = execute_watch_daemon(common_git_dir=common_resolved, gk_pid=gk_pid)
    raise typer.Exit(code=0 if ok else 1)


def main():
    """CLI entrypoint."""
    app()


if __name__ == "__main__":
    main()
