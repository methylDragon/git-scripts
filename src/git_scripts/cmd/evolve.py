"""Core logic for the git-evolve command."""

import pygit2
from rich.console import Group
from rich.panel import Panel

from git_scripts.cmd.rebase_orchestrator import (
    ScriptAbortError,
    handle_interactive_conflict,
)
from git_scripts.cmd.shared import (
    get_ui_worktree_callbacks,
    resolve_branches_to_push,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.reads import (
    format_stack_tree,
    get_repo,
    get_stack_branches,
)
from git_scripts.git.rebase_plan import execute_rebase_plan
from git_scripts.git.remote import push_branches
from git_scripts.git.topology import TopologyAnalyzer
from git_scripts.git.worktrees import manage_worktrees
from git_scripts.models import BranchRebasePlan, RebaseAction, RebaseStatus
from git_scripts.ui import UI


def _find_old_base_via_remote(repo, current_branch_name) -> str | None:
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


def _find_old_base_via_reflog(repo, current_branch_name) -> str | None:
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

        return str(list(log)[0].oid_old)
    except (KeyError, IndexError, pygit2.GitError):
        pass
    return None


def find_old_base(repo_path: str) -> str | None:
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


def _get_current_branch_name(repo: pygit2.Repository) -> str:
    try:
        if not repo.head_is_detached and not repo.head_is_unborn:
            return repo.head.shorthand
    except pygit2.GitError:
        pass
    return ""


def resolve_and_report_old_hash(
    repo: pygit2.Repository, repo_path: str, old_hash: str | None, ui: UI
) -> str | None:
    """Resolves the old hash and reports to the UI if not provided."""
    if not old_hash:
        resolved = find_old_base(repo_path)
        if not resolved:
            ui.print("❌  Error: Could not find previous HEAD in reflog.")
            ui.print("Usage: git-evolve <OLD_HASH>")
            return None
        ui.print(
            f"ℹ️  No hash provided. Auto-detected previous HEAD: {resolved[:7]}"
        )
        return resolved
    try:
        return str(repo.revparse_single(old_hash).id)
    except (KeyError, ValueError):
        ui.print(f"❌  Error: Invalid old hash '{old_hash}'.")
        return None


def _restore_current_branch(repo_path: str, current_branch_name: str) -> None:
    if current_branch_name:
        try:
            run_cmd(["git", "checkout", current_branch_name], cwd=repo_path)
        except GitExecutionError:
            pass


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
                if (
                    repo.merge_base(branch_commit, old_commit.id)
                    != old_commit.id
                ):
                    continue

                if repo.merge_base(new_hash, branch_commit) == pygit2.Oid(
                    hex=new_hash
                ):
                    continue

                orphans.append(branch_name)
            except (KeyError, ValueError, pygit2.GitError):
                pass

    return orphans


def process_single_evolve_stack(
    tip: str,
    repo_path: str,
    repo: pygit2.Repository,
    orphans: list[str],
    analyzer: TopologyAnalyzer,
    new_hash: str,
    resolved_old_hash: str,
    ui: UI,
    failed_branches: set[str],
) -> tuple[bool, list[str]]:
    """Evolves a single stack, returning success status and evolved refs."""
    ui.print(f"🔗  Reconnecting stack '{tip}'...")
    stack_refs = get_stack_branches(repo, tip)

    if any(b in failed_branches for b in stack_refs) or tip in failed_branches:
        ui.print("    [red]⚠️  Skipping due to busy or dirty worktree.[/red]")
        return False, []

    sync_point = analyzer.get_sync_point(tip)

    if sync_point:
        sync_branch, sync_old_hash, sync_new_hash = sync_point
        ui.print(
            f"    ✨  Detected shared history! "
            f"Linking onto updated '{sync_branch}'..."
        )
        plan = BranchRebasePlan(
            branch=tip,
            action=RebaseAction.REBASE_ONTO_SYNC,
            sync_branch=sync_branch,
            sync_old_hash=sync_old_hash,
            sync_new_hash=sync_new_hash,
        )
    else:
        plan = BranchRebasePlan(
            branch=tip,
            action=RebaseAction.REBASE_ONTO_CUT,
            cut_point=resolved_old_hash,
        )

    status = execute_rebase_plan(plan, repo_path, new_hash)

    if status == RebaseStatus.CONFLICT:
        status = handle_interactive_conflict(repo_path, ui, tip)

    successfully_evolved = []
    if status == RebaseStatus.SUCCESS:
        ui.print("    ✅  Success.")
        for ref in stack_refs:
            if ref in orphans:
                successfully_evolved.append(ref)
        return True, successfully_evolved
    else:
        ui.print("    💥 Conflict or error. Aborting...")
        return False, []


def evolve_loop(
    repo_path: str,
    repo: pygit2.Repository,
    orphans: list[str],
    analyzer: TopologyAnalyzer,
    new_hash: str,
    resolved_old_hash: str,
    ui: UI,
) -> tuple[int, list[str], list[str]]:
    """Loops over all tips to evolve them."""
    success_count = 0
    failed_log = []
    successfully_evolved_branches = []

    implicated_branches = set()
    for tip in analyzer.tips:
        implicated_branches.update(get_stack_branches(repo, tip))

    with manage_worktrees(
        active=True,
        repo_path=repo_path,
        target_branches=list(implicated_branches),
        callbacks=get_ui_worktree_callbacks(ui),
    ) as wt_state:
        failed_branches = wt_state.failed_branches
        for tip in analyzer.tips:
            success, evolved_refs = process_single_evolve_stack(
                tip,
                repo_path,
                repo,
                orphans,
                analyzer,
                new_hash,
                resolved_old_hash,
                ui,
                failed_branches,
            )
            if success:
                success_count += 1
                successfully_evolved_branches.extend(evolved_refs)
            else:
                failed_log.append(
                    format_stack_tree(repo, tip, allowed_refs=set(orphans))
                )

    return success_count, failed_log, successfully_evolved_branches


def execute_evolve(
    repo_path: str,
    old_hash: str | None = None,
    ui: UI | None = None,
) -> bool:
    """Rebases displaced stack branches onto the updated base commit."""
    if ui is None:
        ui = UI()

    repo = get_repo(repo_path)
    new_hash = str(repo.revparse_single("HEAD").id)

    current_branch_name = _get_current_branch_name(repo)

    resolved_old_hash = resolve_and_report_old_hash(
        repo, repo_path, old_hash, ui
    )
    if not resolved_old_hash:
        return False

    if resolved_old_hash == new_hash:
        ui.print(
            "✅  HEAD is identical to the target hash. Nothing to evolve."
        )
        return True

    ui.print(
        f"[dim]🔍  Scanning for stacks displaced by move "
        f"from {resolved_old_hash[:7]} to {new_hash[:7]}...[/dim]"
    )

    orphans = _get_orphans(
        repo, resolved_old_hash, new_hash, current_branch_name
    )

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
        indented = "\n".join(
            "        " + line if i > 0 else "    - " + line
            for i, line in enumerate(tree_view.splitlines())
        )
        ui.print(f"[cyan]{indented}[/cyan]")
    ui.print()

    if not ui.confirm("❓  Proceed with evolve?"):
        ui.print("❌  Aborting.")
        return False

    try:
        success_count, failed_log, successfully_evolved_branches = evolve_loop(
            repo_path,
            repo,
            orphans,
            analyzer,
            new_hash,
            resolved_old_hash,
            ui,
        )
    except ScriptAbortError:
        _restore_current_branch(repo_path, current_branch_name)
        return False

    _restore_current_branch(repo_path, current_branch_name)

    ans = _print_evolve_summary(ui, success_count, failed_log)

    if successfully_evolved_branches:
        branches_to_push = list(successfully_evolved_branches)

        if current_branch_name:
            if current_branch_name not in branches_to_push:
                branches_to_push.insert(0, current_branch_name)

        panel_title = (
            f"[bold cyan]Local branches updated/amended "
            f"({len(branches_to_push)})[/bold cyan]"
        )

        ui.print()
        ui.print(
            Panel(
                "\n".join(
                    f"  - [yellow]{b}[/yellow]" for b in branches_to_push
                ),
                title=panel_title,
                border_style="cyan",
                expand=False,
            )
        )

        resolved_branches = resolve_branches_to_push(
            branches=branches_to_push,
            ui=ui,
            prompt_title=(
                "Push "
                f"{ui.pluralize(len(branches_to_push), 'updated branch')} "
                "to origin?"
            ),
        )
        if resolved_branches:
            push_branches(
                branches=resolved_branches,
                options=["--force-with-lease"],
                repo_path=repo_path,
            )

    return ans
