"""Core logic for the git-evolve command."""

from typing import Optional

import pygit2
from rich.console import Group
from rich.panel import Panel

from git_scripts.git.reads import (
    format_stack_tree,
    get_repo,
    get_stack_branches,
)
from git_scripts.git.topology import TopologyAnalyzer
from git_scripts.git.writes import manage_worktrees, rebase_onto
from git_scripts.ui import UI


def _find_old_base_via_remote(repo, current_branch_name) -> Optional[str]:
    if not current_branch_name:
        return None
    try:
        remote_ref = repo.revparse_single(
            f"refs/remotes/origin/{current_branch_name}"
        )
        remote_hash = str(remote_ref.id)

        for branch_name in repo.branches.local:
            if branch_name == current_branch_name:
                continue
            try:
                branch_commit = repo.branches[branch_name].target
                if (
                    repo.merge_base(branch_commit, remote_ref.id)
                    == remote_ref.id
                ):
                    return remote_hash
            except (KeyError, ValueError, pygit2.GitError):
                pass
    except KeyError:
        pass
    return None


def _find_old_base_via_reflog(repo, current_branch_name) -> Optional[str]:
    try:
        log = repo.references["HEAD"].log()
        if not log:
            return None

        for entry in list(log)[:10]:
            historical_hash = str(entry.oid_old)
            try:
                hist_commit = repo.get(historical_hash)
                if not hist_commit:
                    continue

                for branch_name in repo.branches.local:
                    if branch_name == current_branch_name:
                        continue
                    try:
                        branch_commit = repo.branches[branch_name].target
                        if (
                            repo.merge_base(branch_commit, hist_commit.id)
                            == hist_commit.id
                        ):
                            return historical_hash
                    except (KeyError, ValueError, pygit2.GitError):
                        pass
            except (KeyError, ValueError):
                pass

        return str(log[0].oid_old)
    except (KeyError, IndexError, pygit2.GitError):
        pass
    return None


def find_old_base(repo_path: str) -> Optional[str]:
    """Auto-detects the pre-rewrite hash of a target branch.

    When `git-evolve` is run without an explicit `<OLD_HASH>`, it must
    determine where the base branch used to point before it was rewritten.
    This is critical for finding orphaned child branches that are still
    attached to that old state.

    Uses multi-layered heuristics to auto-detect this "movement":
    1. Remote tracking branch: If the local branch has been rewritten but
       not yet pushed, the remote tracking branch (e.g., `origin/main`)
       still points to the exact `old_hash` where the stack branches are
       attached.
    2. Deep Reflog Traversal: If the remote branch is already updated or
       non-existent, we scan the recent `HEAD` reflog. We look for a
       historical hash that serves as a valid merge-base for other local
       branches, indicating that it was the previous root of a stack
       before the rebase occurred.
    """
    repo = get_repo(repo_path)

    current_branch_name = ""
    try:
        if not repo.head_is_detached and not repo.head_is_unborn:
            current_branch_name = repo.head.shorthand
    except pygit2.GitError:
        pass

    ans = _find_old_base_via_remote(repo, current_branch_name)
    if ans:
        return ans

    return _find_old_base_via_reflog(repo, current_branch_name)


def _print_evolve_summary(ui, success_count: int, failed_log: list) -> bool:
    summary_items = []

    if failed_log:
        summary_items.append(
            "[bold red]⚠️  Failed (Manual Fix Needed):[/bold red]"
        )
        for entry in failed_log:
            summary_items.append(
                f"    [red]- {entry.replace(chr(10), chr(10) + '      ')}"
                "[/red]"
            )
    else:
        summary_items.append(
            f"[bold green]✨  All Done! "
            f"({success_count} stacks evolved)[/bold green]"
        )

    ui.print()
    ui.print(
        Panel(
            Group(*summary_items),
            title="[bold]EVOLVE SUMMARY[/bold]",
            border_style="blue",
            expand=False,
        )
    )

    if failed_log:
        ui.print(
            "    [yellow]The repository has been reset to "
            "clean state (per stack).[/yellow]"
        )
        ui.print(
            "    [yellow]The failed stacks require "
            "manual intervention.[/yellow]"
        )
        return False
    return True


def execute_evolve(
    repo_path: str,
    old_hash: Optional[str] = None,
    ui: Optional[UI] = None,
) -> bool:
    """Rebases displaced stack branches onto the updated base commit.

    When an upstream branch is rebased, child branches (stacks) become
    "orphaned" because their base commit is no longer part of the target
    branch's history. This function detects all branches that still point
    to the `old_hash`, calculates where their new base should be relative
    to the updated `HEAD`, and performs `git rebase --update-refs` to
    restore the stack architecture.

    Args:
        repo_path: Path to the git repository.
        old_hash: The previous HEAD hash before the rebase occurred.
            the reflog (HEAD@{1}) will be queried automatically.
        ui: Optional UI instance for output and confirmation prompts.

    Returns:
        True if affected branches rebased or no orphans found.
        False if any rebase operation conflicts or fails.
    """
    if ui is None:
        ui = UI()

    repo = get_repo(repo_path)
    new_hash = str(repo.revparse_single("HEAD").id)

    current_branch_name = ""
    try:
        if not repo.head_is_detached and not repo.head_is_unborn:
            current_branch_name = repo.head.shorthand
    except pygit2.GitError:
        pass

    if not old_hash:
        old_hash = find_old_base(repo_path)
        if not old_hash:
            ui.print("❌  Error: Could not find previous HEAD in reflog.")
            ui.print("Usage: git-evolve <OLD_HASH>")
            return False
        ui.print(
            f"ℹ️  No hash provided. Auto-detected previous HEAD: {old_hash[:7]}"
        )
    else:
        try:
            old_hash = str(repo.revparse_single(old_hash).id)
        except (KeyError, ValueError):
            ui.print(f"❌  Error: Invalid old hash '{old_hash}'.")
            return False

    if old_hash == new_hash:
        ui.print(
            "✅  HEAD is identical to the target hash. Nothing to evolve."
        )
        return True

    ui.print(
        f"[dim]🔍  Scanning for stacks displaced by move "
        f"from {old_hash[:7]} to {new_hash[:7]}...[/dim]"
    )

    orphans = _get_orphans(repo, old_hash, new_hash, current_branch_name)

    if not orphans:
        ui.print("✅  No displaced branches found.")
        return True

    analyzer = TopologyAnalyzer(repo_path, orphans)

    ui.print(
        f"⚡  [bold]Found {len(analyzer.tips)} stack tips[/bold] "
        f"[dim](covering {len(orphans)} branches):[/dim]"
    )
    for tip in analyzer.tips:
        tree_view = format_stack_tree(repo, tip, allowed_refs=set(orphans))
        # Indent it
        indented = "\n".join(
            "        " + line if i > 0 else "    - " + line
            for i, line in enumerate(tree_view.splitlines())
        )
        ui.print(f"[cyan]{indented}[/cyan]")
    ui.print()

    if not ui.confirm("❓  Proceed with evolve?"):
        ui.print("❌  Aborting.")
        return False

    success_count, failed_log = _evolve_stacks(
        repo_path,
        orphans,
        analyzer,
        new_hash,
        old_hash,
        ui,
    )

    return _print_evolve_summary(ui, success_count, failed_log)


def _get_orphans(repo, old_hash, new_hash, current_branch_name) -> list[str]:
    """Finds branches whose merge-base matches the old hash but not the new."""
    orphans = []
    try:
        old_commit = repo.revparse_single(old_hash)
    except (KeyError, ValueError):
        old_commit = None

    if old_commit:
        for branch_name in repo.branches.local:
            if branch_name == current_branch_name:
                continue

            try:
                branch_commit = repo.branches[branch_name].target
                # Check if old_hash is an ancestor of branch
                if (
                    repo.merge_base(branch_commit, old_commit.id)
                    != old_commit.id
                ):
                    continue

                # If new_hash is an ancestor of branch, it's already updated
                if repo.merge_base(new_hash, branch_commit) == pygit2.Oid(
                    hex=new_hash
                ):
                    continue

                orphans.append(branch_name)
            except (KeyError, ValueError, pygit2.GitError):
                pass

    return orphans


def _evolve_stacks(
    repo_path, orphans, analyzer: TopologyAnalyzer, new_hash, old_hash, ui
) -> tuple[int, list[str]]:
    success_count = 0
    failed_log = []

    with manage_worktrees(active=True, repo_path=repo_path) as wt_state:
        failed_branches = wt_state.failed_branches
        for tip in analyzer.tips:
            ui.print(f"🔗 Reconnecting stack '{tip}'...")
            repo = get_repo(repo_path)
            stack_refs = get_stack_branches(repo, tip)

            # Check if any branch in this stack failed to detach
            if (
                any(b in failed_branches for b in stack_refs)
                or tip in failed_branches
            ):
                ui.print(
                    "    [red]⚠️  Skipping due to busy or dirty worktree.[/red]"
                )
                failed_log.append(
                    format_stack_tree(repo, tip, allowed_refs=set(orphans))
                )
                continue

            sync_point = analyzer.get_sync_point(tip)

            rebase_ok = False
            if sync_point:
                sync_branch, sync_old_hash, sync_new_hash = sync_point
                ui.print(
                    f"    ✨  Detected shared history! "
                    f"Linking onto updated '{sync_branch}'..."
                )
                rebase_ok = rebase_onto(
                    sync_new_hash, sync_old_hash, tip, repo_path=repo_path
                )
            else:
                rebase_ok = rebase_onto(
                    new_hash, old_hash, tip, repo_path=repo_path
                )

            if rebase_ok:
                ui.print("    ✅  Success.")
                success_count += 1
            else:
                ui.print("    💥 Conflict. Aborting...")
                failed_log.append(
                    format_stack_tree(repo, tip, allowed_refs=set(orphans))
                )

    return success_count, failed_log
