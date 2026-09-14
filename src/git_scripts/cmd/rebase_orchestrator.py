"""Core logic for orchestrating single-branch rebases."""

import pygit2
from rich.console import Group
from rich.panel import Panel
from rich.progress import Progress

from git_scripts.cmd.shared import get_ui_worktree_callbacks
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.reads import (
    format_stack_tree,
    get_stack_branches,
    is_obsolete,
)
from git_scripts.git.rebase import (
    rebase_abort,
    rebase_continue,
)
from git_scripts.git.rebase_plan import create_rebase_plan, execute_rebase_plan
from git_scripts.git.topology import TopologyAnalyzer, sync_colocated_branches
from git_scripts.git.worktrees import (
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
) -> RebaseStatus:
    """Handles an interactive rebase conflict loop."""
    branch_msg = f" on branch '[bold]{branch}[/bold]'" if branch else ""
    ui.print(f"    [red]❌  Conflict detected{branch_msg}.[/red]")

    with ui.suspend_progress():
        while True:
            ans = ui.ask_choice(
                "How would you like to handle this?",
                choices=[
                    "Abort rebase and rollback",
                    "Resolve manually, then continue",
                    "Abort script without rollback",
                ],
                default="Abort rebase and rollback",
            )

            match ans:
                case "Abort script without rollback":
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

                    status = rebase_continue(repo_path)
                    if status == RebaseStatus.SUCCESS:
                        ui.print(
                            "    ✅  Rebase finished. Continuing script..."
                        )
                        return RebaseStatus.SUCCESS
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
                                return RebaseStatus.SUCCESS
                            else:
                                ui.print("    ❌  Rebase marked as aborted.")
                                rebase_abort(repo_path)
                                return RebaseStatus.ERROR

                        ui.print(
                            "    [red]⚠️  Rebase could not continue. "
                            "Check if conflicts are truly resolved.[/red]"
                        )
                        continue
                case _:
                    rebase_abort(repo_path)
                    return RebaseStatus.ERROR


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
                    f"\n[yellow]⚠️  Warning: Branch "
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


def rebase_single_branch(
    branch: str,
    config: BatchRebaseConfig,
    failed_branches: set[str],
    ui: UI,
) -> SingleBranchResult:
    """Attempts to rebase a single branch during batch rebasing."""
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
            format_stack_tree(
                repo,
                branch,
                config.prefix,
                config.target,
                False,
                config.branch_pool,
            )
        )
        return result

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
        return result

    status = execute_rebase_plan(plan, config.repo_path, config.target)

    if status == RebaseStatus.CONFLICT:
        status = handle_interactive_conflict(config.repo_path, ui, branch)

    if status == RebaseStatus.SUCCESS:
        try:
            repo = pygit2.Repository(config.repo_path)
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
        except Exception:
            pass
    else:
        result.failed_log.append(
            format_stack_tree(
                repo,
                branch,
                config.prefix,
                config.target,
                False,
                config.branch_pool,
            )
        )

    return result


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

    with manage_worktrees(
        prefix=prefix,
        active=all_worktrees,
        repo_path=repo_path,
        target_branches=list(branch_pool),
        callbacks=get_ui_worktree_callbacks(ui),
    ) as wt_state:
        failed_branches = wt_state.failed_branches
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

                    branch_res = rebase_single_branch(
                        branch,
                        config,
                        failed_branches,
                        ui,
                    )

                    batch_result.aggregate(branch_res)
                    progress.advance(task)

            except ScriptAbortError:
                ui.active_progress = None
                return batch_result, False
            finally:
                ui.active_progress = None

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


def prompt_and_delete_merged(
    result: SingleBranchResult, auto_delete: bool, ui: UI, repo_path: str
):
    """Prompts and deletes merged branches."""
    unique_to_delete = sorted(
        result.branches_to_delete - result.branches_to_keep
    )
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

        action = ui.ask_choice(
            "❓  Delete the {}?".format(
                ui.pluralize(
                    len(unique_to_delete), "fully merged local branch"
                )
            ),
            choices=["Skip all", "Select which to delete", "Delete all"],
            default="Skip all",
        )

        match action:
            case "Delete all":
                selected_to_delete = unique_to_delete
            case "Select which to delete":
                selected_to_delete = ui.ask_checkbox(
                    "Select {} to delete:".format(
                        ui.pluralize(
                            len(unique_to_delete), "fully merged local branch"
                        )
                    ),
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
