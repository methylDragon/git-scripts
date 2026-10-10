"""Core logic for orchestrating single-branch and batch rebases."""

import time

import pygit2
from rich.console import Group
from rich.panel import Panel
from rich.progress import Progress

from git_scripts.cmd.shared import (
    get_ui_worktree_callbacks,
    restore_branch,
    select_branches_to_delete,
)
from git_scripts.cmd.shared import (
    prompt_and_push_updated_branches as _prompt_and_push,
)
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.reads import (
    format_stack_tree,
    get_stack_branches,
    is_obsolete,
)
from git_scripts.git.rebase import rebase_abort, rebase_continue
from git_scripts.git.rebase_plan import create_rebase_plan, execute_rebase_plan
from git_scripts.git.remote import push_branches
from git_scripts.git.topology import TopologyAnalyzer, sync_colocated_branches
from git_scripts.git.worktrees import (
    detach_worktrees,
    is_in_another_worktree,
    is_worktree_busy,
    manage_worktrees,
)
from git_scripts.models import (
    BatchRebaseConfig,
    RebaseAction,
    RebaseStatus,
    ScriptAbortError,
    SingleBranchResult,
)
from git_scripts.ui import UI


def handle_interactive_conflict(
    repo_path: str, ui: UI, branch: str
) -> tuple[RebaseStatus, str | None]:
    """Handles an interactive rebase conflict loop."""
    branch_msg = f" on branch '[bold]{branch}[/bold]'" if branch else ""
    ui.print(f"    [red]❌  Conflict detected{branch_msg}.[/red]")

    with ui.suspend_progress():
        while True:
            ans = ui.ask_choice(
                "How would you like to handle this?",
                choices=[
                    "Rollback stack and skip to next",
                    "Resolve manually, then continue",
                    "Exit script without rollback",
                ],
                default="Rollback stack and skip to next",
            )

            match ans:
                case "Exit script without rollback":
                    ui.print(
                        "    [yellow]Leaving repository in current state "
                        "(rebase in progress).[/yellow]"
                    )
                    raise ScriptAbortError(
                        "User aborted script during conflict."
                    )
                case "Resolve manually, then continue":
                    ui.print(
                        "    [yellow]Please resolve the conflicts in another "
                        "terminal.\n    (DO NOT run "
                        "`git rebase --continue`)[/yellow]"
                    )
                    ui.pause(
                        "    [cyan]When the conflicts are completely "
                        "resolved, press \\[[bold]ENTER[/bold]]...[/cyan]"
                    )

                    status, err_msg = rebase_continue(repo_path)
                    if status == RebaseStatus.SUCCESS:
                        ui.print(
                            "    ✅  Rebase finished. Continuing script..."
                        )
                        return RebaseStatus.SUCCESS, None
                    else:
                        if not is_worktree_busy(repo_path):
                            ui.print(
                                "    [yellow]⚠️  No active rebase detected.\n"
                                "    It seems you may have already run "
                                "`git rebase --continue` or `--abort` "
                                "manually.[/yellow]"
                            )
                            ans2 = ui.ask_choice(
                                "Did you successfully complete the rebase?",
                                choices=["Yes", "No (Treat as aborted)"],
                                default="Yes",
                            )
                            if ans2 == "Yes":
                                ui.print(
                                    "    ✅  Rebase assumed finished. "
                                    "Continuing script..."
                                )
                                return RebaseStatus.SUCCESS, None
                            else:
                                ui.print("    ❌  Rebase marked as aborted.")
                                rebase_abort(repo_path)
                                return RebaseStatus.ERROR, None

                        ui.print(
                            "    [red]⚠️  Rebase could not continue. "
                            "Check if conflicts are truly resolved.[/red]"
                        )
                        continue
                case _:
                    rebase_abort(repo_path)
                    return RebaseStatus.ERROR, None


def check_and_report_worktree_blocks(
    repo_path: str,
    branch: str,
    stack_refs: set[str],
    all_worktrees: bool,
    failed_branches: set[str],
    ui: UI,
) -> bool:
    """Reports if a branch or its stack is blocked by worktree constraints."""
    if not all_worktrees:
        for ref in stack_refs:
            if is_in_another_worktree(repo_path, ref):
                ui.print(
                    "\n[yellow]⚠️  Warning: Branch "
                    f"'[bold]{ref}[/bold]'"
                    " in stack is checked out in another "
                    "worktree.[/yellow]"
                )
                ui.print(
                    "[yellow]  Skipping stack. (Use "
                    "--all-worktrees to automatically rebase "
                    "across worktrees)[/yellow]\n"
                )
                return True

    fail = branch in failed_branches
    fail = fail or any(b in failed_branches for b in stack_refs)
    if fail:
        ui.print("    [red]⚠️  Skipping due to busy or dirty worktree.[/red]")
        return True

    return False


def _record_rebase_success(
    branch: str,
    pre_stack_refs: set[str],
    config: BatchRebaseConfig,
    result: SingleBranchResult,
) -> None:
    """Records updated, obsolete, and co-located branches after a rebase."""
    try:
        repo = pygit2.Repository(config.repo_path)
        stack_refs = pre_stack_refs | get_stack_branches(
            repo, branch, config.prefix, branch_pool=config.branch_pool
        )
        sync_colocated_branches(
            repo, branch, stack_refs, config.analyzer, config.repo_path
        )

        for ref in stack_refs:
            try:
                act_hash = str(repo.revparse_single(ref).id)
            except KeyError:
                continue
            if is_obsolete(repo, pygit2.Oid(hex=act_hash), config.target):
                result.branches_to_delete.add(ref)
            else:
                result.branches_to_keep.add(ref)

        result.success_log.append(
            format_stack_tree(
                repo,
                branch,
                config.prefix,
                config.target,
                True,
                config.branch_pool,
            )
        )
    except (KeyError, ValueError, pygit2.GitError, GitExecutionError):
        pass


def _record_rebase_failure(
    repo: pygit2.Repository,
    branch: str,
    config: BatchRebaseConfig,
    err_msg: str | None,
) -> str:
    """Cleans up any wedged rebase state and formats a failure tree entry."""
    if is_worktree_busy(config.repo_path):
        rebase_abort(config.repo_path)

    tree_str = format_stack_tree(
        repo,
        branch,
        config.prefix,
        config.target,
        False,
        config.branch_pool,
    )
    if err_msg:
        indented_err = "\n".join(
            "      " + line for line in err_msg.splitlines()
        )
        tree_str += f"\n{indented_err}"
    return tree_str


def rebase_single_branch(
    branch: str,
    config: BatchRebaseConfig,
    failed_branches: set[str],
    ui: UI,
) -> tuple[SingleBranchResult, bool]:
    """Attempts to rebase a single branch in Pass 1, deferring conflicts."""
    result = SingleBranchResult()
    repo = pygit2.Repository(config.repo_path)
    stack_refs = get_stack_branches(
        repo, branch, config.prefix, branch_pool=config.branch_pool
    )

    if check_and_report_worktree_blocks(
        config.repo_path,
        branch,
        stack_refs,
        config.all_worktrees,
        failed_branches,
        ui,
    ):
        result.failed_log.append(
            _record_rebase_failure(repo, branch, config, None)
        )
        return result, False

    plan = create_rebase_plan(config.analyzer, branch)

    if plan.action == RebaseAction.SKIP:
        result.skipped_log.append(
            format_stack_tree(
                repo,
                branch,
                config.prefix,
                config.target,
                False,
                config.branch_pool,
            )
        )
        result.branches_to_delete.update(stack_refs)
        return result, False

    status, err_msg = execute_rebase_plan(
        plan, config.repo_path, config.target
    )

    if status == RebaseStatus.CONFLICT:
        rebase_abort(config.repo_path)
        ui.print(
            "    [yellow]⏸️  Conflict detected on branch "
            f"'[bold]{branch}[/bold]'. Rolling back and deferring to "
            "second pass...[/yellow]"
        )
        return result, True

    if status == RebaseStatus.SUCCESS:
        _record_rebase_success(branch, stack_refs, config, result)
    else:
        result.failed_log.append(
            _record_rebase_failure(repo, branch, config, err_msg)
        )

    return result, False


def resolve_conflicted_branch(
    branch: str,
    config: BatchRebaseConfig,
    ui: UI,
) -> SingleBranchResult:
    """Re-attempts a deferred branch in Pass 2 with interactive resolution."""
    result = SingleBranchResult()
    repo = pygit2.Repository(config.repo_path)
    stack_refs = get_stack_branches(
        repo, branch, config.prefix, branch_pool=config.branch_pool
    )

    plan = create_rebase_plan(config.analyzer, branch)
    status, err_msg = execute_rebase_plan(
        plan, config.repo_path, config.target
    )

    if status == RebaseStatus.CONFLICT:
        status, err_msg = handle_interactive_conflict(
            config.repo_path, ui, branch
        )

    if status == RebaseStatus.SUCCESS:
        _record_rebase_success(branch, stack_refs, config, result)
    else:
        failure_msg = err_msg if status != RebaseStatus.CONFLICT else None
        result.failed_log.append(
            _record_rebase_failure(repo, branch, config, failure_msg)
        )

    return result


def _run_conflict_resolution_pass(
    deferred_branches: list[str],
    config: BatchRebaseConfig,
    ui: UI,
    batch_result: SingleBranchResult,
) -> None:
    """Runs the second pass to interactively resolve deferred conflicts."""
    if not deferred_branches:
        return

    total_conflicts = len(deferred_branches)
    stack_word = ui.pluralize(total_conflicts, "conflicted stack")
    ui.print(
        f"\n[bold yellow]⚠️  Pass 2: Resolving {stack_word}...[/bold yellow]"
    )
    for i, branch in enumerate(deferred_branches, 1):
        ui.print(
            f"\n[cyan]🔄  Conflicted Stack ({i}/{total_conflicts}): "
            f"[bold]{branch}[/bold][/cyan]"
        )
        branch_res = resolve_conflicted_branch(branch, config, ui)
        batch_result.aggregate(branch_res)


def rebase_loop(
    analyzer: TopologyAnalyzer,
    repo_path: str,
    prefix: str,
    target: str,
    all_worktrees: bool,
    ui: UI,
    branch_pool: set[str],
) -> tuple[SingleBranchResult, bool]:
    """Helper to run the inner rebase loop for batch processing."""
    batch_result = SingleBranchResult()

    config = BatchRebaseConfig(
        repo_path=repo_path,
        prefix=prefix,
        target=target,
        all_worktrees=all_worktrees,
        analyzer=analyzer,
        branch_pool=branch_pool,
    )

    try:
        with manage_worktrees(
            prefix=prefix,
            active=all_worktrees,
            repo_path=repo_path,
            target_branches=list(branch_pool),
            callbacks=get_ui_worktree_callbacks(ui),
        ) as wt_state:
            failed_branches = wt_state.failed_branches
            deferred_branches: list[str] = []
            with Progress(console=ui.console, transient=True) as progress:
                ui.active_progress = progress
                total_tips = len(analyzer.tips)
                task = progress.add_task(
                    "[cyan]Rebasing stacks...", total=total_tips
                )
                try:
                    for i, branch in enumerate(analyzer.tips, 1):
                        progress.update(
                            task,
                            description=(
                                f"[cyan]Processing Stack ({i}/{total_tips}): "
                                f"{branch}..."
                            ),
                        )

                        branch_res, deferred = rebase_single_branch(
                            branch,
                            config,
                            failed_branches,
                            ui,
                        )

                        batch_result.aggregate(branch_res)
                        if deferred:
                            deferred_branches.append(branch)
                        progress.advance(task)
                finally:
                    ui.active_progress = None

            _run_conflict_resolution_pass(
                deferred_branches, config, ui, batch_result
            )
    except ScriptAbortError:
        return batch_result, False

    return batch_result, True


def print_batch_summary(ui: UI, result: SingleBranchResult) -> None:
    """Formats and prints the batch summary panel."""
    summary_items = []

    if result.success_log:
        summary_items.append("[bold green]✅  Updated Stacks:[/bold green]")
        for entry in result.success_log:
            entry_fmt = entry.replace(chr(10), chr(10) + "      ")
            summary_items.append(f"    [cyan]- {entry_fmt}[/cyan]")
        summary_items.append("")

    if result.skipped_log:
        summary_items.append(
            "[bold dim white]💤  Skipped (Fully Merged):[/bold dim white]"
        )
        for entry in result.skipped_log:
            entry_fmt = entry.replace(chr(10), chr(10) + "      ")
            summary_items.append(f"    [dim white]- {entry_fmt}[/dim white]")
        summary_items.append("")

    if result.failed_log:
        summary_items.append(
            "[bold red]⚠️  Failed (Manual Fix Needed):[/bold red]"
        )
        for entry in result.failed_log:
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


def _checkout_target_or_detach(
    repo_path: str, target: str, branches_to_delete: set[str]
) -> None:
    """Moves repo_path off a branch scheduled for deletion."""
    if (
        target
        and target not in branches_to_delete
        and not is_in_another_worktree(repo_path, target)
    ):
        try:
            run_cmd(["git", "checkout", target], cwd=repo_path)
            return
        except GitExecutionError:
            pass

    try:
        run_cmd(["git", "checkout", "--detach"], cwd=repo_path)
    except GitExecutionError:
        pass


def _release_worktrees_for_deletion(
    repo_path: str,
    branches_to_delete: set[str],
    target: str,
    ui: UI,
) -> None:
    """Ensures no branch in branches_to_delete remains checked out."""
    try:
        current = run_cmd(["git", "branch", "--show-current"], cwd=repo_path)
    except GitExecutionError:
        current = ""

    if current in branches_to_delete:
        _checkout_target_or_detach(repo_path, target, branches_to_delete)

    detach_worktrees(
        repo_path=repo_path,
        target_branches=list(branches_to_delete),
        callbacks=get_ui_worktree_callbacks(ui),
        save_state=False,
    )


def _find_deleted_branches(repo_path: str, candidates: list[str]) -> list[str]:
    """Returns candidate branches that no longer exist in repo_path."""
    try:
        repo = pygit2.Repository(repo_path)
        remaining = set(repo.branches.local)
        return [b for b in candidates if b not in remaining]
    except (KeyError, ValueError, pygit2.GitError):
        return []


def _print_deleted_branches_panel(deleted: list[str], ui: UI) -> None:
    """Prints the Deleted Branches summary panel."""
    if not deleted:
        return
    deleted_list = "\n".join(f"  [red]- {b}[/red]" for b in deleted)
    ui.print(
        Panel(
            deleted_list,
            title="[bold red]Deleted Branches[/bold red]",
            border_style="red",
            expand=False,
        )
    )


def prompt_and_delete_merged(
    result: SingleBranchResult,
    auto_delete: bool,
    ui: UI,
    repo_path: str,
    target: str = "main",
) -> None:
    """Prompts and deletes merged branches."""
    unique_to_delete = sorted(
        result.branches_to_delete - result.branches_to_keep
    )
    if not unique_to_delete:
        return

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
        merged_label = ui.pluralize(
            len(unique_to_delete), "fully merged local branch"
        )
        selected_to_delete = select_branches_to_delete(
            unique_to_delete,
            f"❓  Delete the {merged_label}?",
            f"Select {merged_label} to delete:",
            ui,
            default="Skip all",
        )

    if not selected_to_delete:
        return

    _release_worktrees_for_deletion(
        repo_path, set(selected_to_delete), target, ui
    )

    try:
        run_cmd(["git", "branch", "-D"] + selected_to_delete, cwd=repo_path)
        _print_deleted_branches_panel(selected_to_delete, ui)
    except GitExecutionError as err:
        ui.print(f"[red]⚠️  Failed to delete branches: {err}[/red]")
        deleted = _find_deleted_branches(repo_path, selected_to_delete)
        _print_deleted_branches_panel(deleted, ui)


def prompt_and_push_updated_branches(
    branches_to_keep: set[str] | list[str], repo_path: str, ui: UI
) -> None:
    """Displays updated branches and prompts to push with force-with-lease."""
    _prompt_and_push(
        branches_to_keep,
        repo_path,
        ui,
        push_fn=push_branches,
    )


def _restore_start_branch_or_target(
    repo_path: str, start_branch: str, target: str
) -> None:
    """Restores start_branch if still present, or falls back to target."""
    if not start_branch:
        return
    try:
        if start_branch in pygit2.Repository(repo_path).branches.local:
            restore_branch(repo_path, start_branch)
            return
    except (KeyError, ValueError, pygit2.GitError):
        pass
    _checkout_target_or_detach(repo_path, target, set())


def execute_batch_rebase(
    repo_path: str,
    branches: list[str],
    target: str,
    ui: UI,
    *,
    prefix: str = "",
    start_branch: str = "",
    all_worktrees: bool = False,
    auto_delete: bool = False,
) -> bool:
    """Runs topology analysis, batch rebase, pruning, and push prompts."""
    analyzer = TopologyAnalyzer(repo_path, branches)
    ui.print(f"  [bold]Found {len(analyzer.tips)} stack tips.[/bold]")

    start_time = time.monotonic()
    analyzer.analyze_obsolescence(
        target,
        progress_callback=lambda msg: ui.print(f"  [dim]⏳ {msg}[/dim]"),
    )
    elapsed = time.monotonic() - start_time
    ui.print(f"  [dim]⏱️  Topology analysis completed in {elapsed:.2f}s[/dim]")

    if all_worktrees:
        ui.print(
            "[dim]🔄  Detaching worktrees for cross-worktree rebase...[/dim]"
        )

    batch_result, completed = rebase_loop(
        analyzer,
        repo_path,
        prefix,
        target,
        all_worktrees,
        ui,
        set(branches),
    )
    if not completed:
        return False

    print_batch_summary(ui, batch_result)
    prompt_and_delete_merged(
        batch_result, auto_delete, ui, repo_path, target=target
    )
    _restore_start_branch_or_target(repo_path, start_branch, target)

    prompt_and_push_updated_branches(
        batch_result.branches_to_keep, repo_path, ui
    )
    return len(batch_result.failed_log) == 0
