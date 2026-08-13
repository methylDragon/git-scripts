"""Core logic for the git-rebase-prefix command."""

import time

import pygit2
from rich.console import Group
from rich.panel import Panel
from rich.progress import Progress

from git_scripts.git.reads import (
    format_stack_tree,
    get_stack_branches,
    is_obsolete,
)
from git_scripts.git.topology import TopologyAnalyzer
from git_scripts.git.writes import (
    GitExecutionError,
    is_in_another_worktree,
    manage_worktrees,
    prompt_and_push_branches,
    rebase_onto,
    rebase_standard,
    run_cmd,
    update_target,
)
from git_scripts.models import BranchRebaseResult, RebaseAction
from git_scripts.ui import UI


def _find_matching_branches(repo, prefix: str, target: str) -> list[str]:
    """Finds all local branches matching the prefix."""
    all_branches = []
    for ref in repo.references:
        if ref.startswith(f"refs/heads/{prefix}"):
            short_name = ref[len("refs/heads/") :]
            if short_name != target:
                all_branches.append(short_name)
    return all_branches


def _print_batch_summary(ui, success_log, skipped_log, failed_log) -> None:
    """Formats and prints the batch summary panel."""
    summary_items = []

    if success_log:
        summary_items.append("[bold green]✅  Updated Stacks:[/bold green]")
        for entry in success_log:
            entry_fmt = entry.replace(chr(10), chr(10) + "      ")
            summary_items.append(f"    [cyan]- {entry_fmt}[/cyan]")
        summary_items.append("")

    if skipped_log:
        summary_items.append(
            "[bold dim white]💤  Skipped (Fully Merged):[/bold dim white]"
        )
        for entry in skipped_log:
            entry_fmt = entry.replace(chr(10), chr(10) + "      ")
            summary_items.append(f"    [dim white]- {entry_fmt}[/dim white]")
        summary_items.append("")

    if failed_log:
        summary_items.append(
            "[bold red]⚠️  Failed (Manual Fix Needed):[/bold red]"
        )
        for entry in failed_log:
            entry_fmt = entry.replace(chr(10), chr(10) + "      ")
            summary_items.append(f"    [red]- {entry_fmt}[/red]")
        summary_items.append("")

    if summary_items:
        summary_items.pop()  # remove trailing empty string

    ui.print()
    ui.print(
        Panel(
            Group(*summary_items),
            title="[bold]BATCH SUMMARY[/bold]",
            border_style="blue",
            expand=False,
        )
    )


def execute_rebase_prefix(
    repo_path: str,
    prefix: str,
    target: str = "main",
    all_worktrees: bool = False,
    auto_delete: bool = False,
    ui: UI | None = None,
) -> bool:
    """Executes the rebase-prefix command to batch rebase stack branches.

    Scans the repository for all branches matching the given `prefix`,
    determines their optimal rebase strategy relative to the `target`
    branch, and applies it.

    This function utilizes three distinct rebase strategies:
    - skip: The branch is fully merged into the target.
    - rebase_onto_sync: The branch depends on another stack branch that
      has moved, so we re-link it to the new hash of its dependency.
    - rebase_onto_cut: The branch's base commit has been squashed into
      the target, so we cut it at the obsolete boundary.
    - rebase_standard: A standard rebase onto the target tip.

    Args:
        repo_path: Path to the repository.
        prefix: Branch prefix to match (e.g., 'feat/').
        target: The target upstream branch (defaults to 'main').
        all_worktrees: If True, detaches branches checked out in other
            worktrees before rebasing to avoid git lock errors.
        auto_delete: If True, fully merged branches are deleted.
        ui: Optional UI instance for output and confirmation prompts.

    Returns:
        True if all matching branches were processed without conflicts.
    """
    if ui is None:
        ui = UI()

    if not prefix:
        ui.print("Error: Missing <prefix>.")
        return False

    repo = pygit2.Repository(repo_path)
    start_branch = ""
    try:
        if not repo.head_is_detached and not repo.head_is_unborn:
            start_branch = repo.head.shorthand
    except pygit2.GitError:
        pass

    if not update_target(repo_path, target, ui):
        if start_branch:
            try:
                run_cmd(["git", "checkout", start_branch], cwd=repo_path)
            except GitExecutionError:
                pass
        return False

    ui.print(f"[dim]🔍  Scanning 'refs/heads/{prefix}*'...[/dim]")

    all_branches = _find_matching_branches(repo, prefix, target)

    if not all_branches:
        ui.print("  [yellow]No matching branches found.[/yellow]")
        return True

    analyzer = TopologyAnalyzer(repo_path, all_branches)
    ui.print(f"  [bold]Found {len(analyzer.tips)} stack tips.[/bold]")

    start_time = time.time()
    analyzer.analyze_obsolescence(target, ui=ui)
    elapsed = time.time() - start_time
    ui.print(f"  [dim]⏱️  Topology analysis completed in {elapsed:.2f}s[/dim]")

    success_log = []
    skipped_log = []
    failed_log = []
    branches_to_delete: set[str] = set()
    branches_to_keep: set[str] = set()

    if all_worktrees:
        ui.print(
            "[dim]🔄  Detaching worktrees for cross-worktree rebase...[/dim]"
        )

    with manage_worktrees(
        prefix, active=all_worktrees, repo_path=repo_path
    ) as wt_state:
        failed_branches = wt_state.failed_branches
        with Progress(console=ui.console, transient=True) as progress:
            total_tips = len(analyzer.tips)
            task = progress.add_task(
                "[cyan]Rebasing stacks...", total=total_tips
            )
            for i, branch in enumerate(analyzer.tips, 1):
                progress.update(
                    task,
                    description=(
                        f"[cyan]Processing Stack ({i}/{total_tips}): "
                        f"{branch}..."
                    ),
                )
                _process_branch_rebase(
                    branch,
                    repo_path,
                    prefix,
                    target,
                    all_worktrees,
                    failed_branches,
                    analyzer,
                    failed_log,
                    skipped_log,
                    success_log,
                    branches_to_delete,
                    branches_to_keep,
                    ui,
                )
                progress.advance(task)

    _print_batch_summary(ui, success_log, skipped_log, failed_log)

    _delete_merged(
        branches_to_delete, branches_to_keep, auto_delete, ui, repo_path
    )

    if start_branch:
        try:
            run_cmd(["git", "checkout", start_branch], cwd=repo_path)
        except GitExecutionError:
            pass

    if branches_to_keep:
        prompt_and_push_branches(
            branches=list(branches_to_keep),
            ui=ui,
            push_opts=["--force-with-lease"],
            repo_path=repo_path,
            prompt_title=(
                f"Push {len(branches_to_keep)} updated branches to origin?"
            ),
            panel_title=(
                f"[bold cyan]Local branches updated "
                f"({len(branches_to_keep)})[/bold cyan]"
            ),
        )

    return len(failed_log) == 0


def _determine_rebase_strategy(
    analyzer: TopologyAnalyzer, branch: str
) -> BranchRebaseResult:
    analysis_data = analyzer.get_analysis(branch)
    if analysis_data.is_obsolete:
        return BranchRebaseResult(
            branch=branch, action=RebaseAction.SKIP, reason="Fully merged"
        )

    sync_point = analyzer.get_sync_point(branch)
    if sync_point:
        return BranchRebaseResult(
            branch=branch,
            action=RebaseAction.REBASE_ONTO_SYNC,
            sync_branch=sync_point[0],
            sync_old_hash=sync_point[1],
            sync_new_hash=sync_point[2],
        )

    cut_point = analysis_data.cut_point
    if cut_point:
        return BranchRebaseResult(
            branch=branch,
            action=RebaseAction.REBASE_ONTO_CUT,
            cut_point=cut_point,
        )

    return BranchRebaseResult(
        branch=branch, action=RebaseAction.REBASE_STANDARD
    )


def _sync_colocated_branches(
    repo: pygit2.Repository,
    branch: str,
    stack_refs: set[str],
    analyzer: TopologyAnalyzer,
    repo_path: str,
) -> None:
    """Fast-forward co-located alias branches sharing the exact same commit."""
    new_tip_commit = repo.revparse_single(branch)
    analyzer_old_commit_hash = analyzer.initial_ref_map.get(branch)
    new_id_str = str(new_tip_commit.id)

    if not analyzer_old_commit_hash or new_id_str == analyzer_old_commit_hash:
        return

    for ref in stack_refs:
        if ref == branch:
            continue
        ref_old_hash = analyzer.initial_ref_map.get(ref)
        if ref_old_hash == analyzer_old_commit_hash:
            try:
                run_cmd(
                    ["git", "branch", "-f", ref, new_id_str], cwd=repo_path
                )
            except GitExecutionError:
                pass


def _process_branch_rebase(
    branch,
    repo_path,
    prefix,
    target,
    all_worktrees,
    failed_branches,
    analyzer: TopologyAnalyzer,
    failed_log,
    skipped_log,
    success_log,
    branches_to_delete,
    branches_to_keep,
    ui,
):
    repo = pygit2.Repository(repo_path)
    stack_refs = get_stack_branches(repo, branch, prefix)

    if not all_worktrees:
        blocking_branch = None
        for ref in stack_refs:
            if is_in_another_worktree(repo_path, ref):
                blocking_branch = ref
                break

        if blocking_branch:
            ui.print(
                f"\n[yellow]⚠️  Warning: Branch "
                f"'[bold]{blocking_branch}[/bold]'"
                " in stack is checked out in another worktree.[/yellow]"
            )
            ui.print(
                "[yellow]  Skipping stack. (Use --all-worktrees to "
                "automatically rebase across worktrees)[/yellow]\n"
            )
            failed_log.append(
                format_stack_tree(
                    repo, branch, prefix, target, filter_merged_in_target=False
                )
            )
            return

    if (
        any(b in failed_branches for b in stack_refs)
        or branch in failed_branches
    ):
        ui.print("    [red]⚠️  Skipping due to busy or dirty worktree.[/red]")
        failed_log.append(
            format_stack_tree(
                repo, branch, prefix, target, filter_merged_in_target=False
            )
        )
        return

    res = _determine_rebase_strategy(analyzer, branch)

    if res.action == RebaseAction.SKIP:
        skipped_log.append(
            format_stack_tree(
                repo, branch, prefix, target, filter_merged_in_target=False
            )
        )
        for ref in stack_refs:
            branches_to_delete.add(ref)
        return

    rebase_ok = _apply_rebase_strategy(res, branch, target, repo_path, ui)

    if rebase_ok:
        try:
            repo = pygit2.Repository(repo_path)

            _sync_colocated_branches(
                repo, branch, stack_refs, analyzer, repo_path
            )

            for ref in stack_refs:
                try:
                    actual_hash = str(repo.revparse_single(ref).id)
                except KeyError:
                    continue
                # If the branch is fully merged into target
                # (e.g. hash == target, or it's an ancestor like
                # main~1 left behind by git rebase), we can safely mark
                # it for deletion.
                if is_obsolete(repo, pygit2.Oid(hex=actual_hash), target):
                    branches_to_delete.add(ref)
                    branches_to_keep.discard(ref)
                else:
                    branches_to_keep.add(ref)

            success_log.append(
                format_stack_tree(
                    repo, branch, prefix, target, filter_merged_in_target=True
                )
            )
        except Exception:
            pass
    else:
        failed_log.append(
            format_stack_tree(
                repo, branch, prefix, target, filter_merged_in_target=False
            )
        )


def _apply_rebase_strategy(res, branch, target, repo_path, ui) -> bool:
    """Dispatches the correct pygit2 rebase operation based on analysis."""
    try:
        match res.action:
            case RebaseAction.REBASE_ONTO_SYNC if (
                res.sync_new_hash and res.sync_old_hash
            ):
                return rebase_onto(
                    res.sync_new_hash,
                    res.sync_old_hash,
                    branch,
                    repo_path=repo_path,
                    ui=ui,
                )
            case RebaseAction.REBASE_ONTO_CUT if res.cut_point:
                return rebase_onto(
                    target, res.cut_point, branch, repo_path=repo_path, ui=ui
                )
            case RebaseAction.REBASE_STANDARD:
                return rebase_standard(
                    target, branch, repo_path=repo_path, ui=ui
                )
            case _:
                return False
    except GitExecutionError as e:
        # Extract just the useful git stderr from our custom exception
        err_msg = str(e)
        if "Error:" in err_msg:
            err_msg = err_msg.split("Error:", 1)[1].strip()

        ui.print(f"    [red]❌  Conflict or error. Aborting.\n{err_msg}[/red]")
        return False


def _delete_merged(
    branches_to_delete, branches_to_keep, auto_delete, ui, repo_path
):
    unique_to_delete = sorted(branches_to_delete - branches_to_keep)
    if not unique_to_delete:
        return

    selected_to_delete = []

    if auto_delete or ui.auto_yes:
        selected_to_delete = unique_to_delete
    else:
        branch_list = "\n".join(
            f"  - [cyan]{b}[/cyan]" for b in unique_to_delete
        )
        ui.print(
            Panel(
                branch_list,
                title="[bold yellow]Fully Merged Branches[/bold yellow]",
                border_style="yellow",
                expand=False,
            )
        )

        word = "branch" if len(unique_to_delete) == 1 else "branches"
        action = ui.ask_choice(
            f"❓  Delete the {len(unique_to_delete)} "
            f"fully merged local {word}?",
            choices=["Skip all", "Select which to delete", "Delete all"],
            default="Skip all",
        )

        match action:
            case "Delete all":
                selected_to_delete = unique_to_delete
            case "Select which to delete":
                selected_to_delete = ui.ask_checkbox(
                    f"Select fully merged local {word} to delete:",
                    choices=unique_to_delete,
                )
            case _:
                selected_to_delete = []

    if selected_to_delete:
        try:
            run_cmd(
                ["git", "branch", "-D"] + selected_to_delete, cwd=repo_path
            )
            deleted_list = "\n".join(
                f"  [red]- {b}[/red]" for b in selected_to_delete
            )
            ui.print(
                Panel(
                    deleted_list,
                    title="[bold red]Deleted Branches[/bold red]",
                    border_style="red",
                    expand=False,
                )
            )
        except GitExecutionError:
            pass
