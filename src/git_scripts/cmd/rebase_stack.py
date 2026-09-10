"""Core logic for the git-rebase-stack command."""

import time

import pygit2
from rich.panel import Panel

from git_scripts.cmd.rebase_orchestrator import (
    print_batch_summary,
    prompt_and_delete_merged,
    rebase_loop,
)
from git_scripts.cmd.shared import resolve_branches_to_push, ui_update_target
from git_scripts.git.core import GitExecutionError, run_cmd
from git_scripts.git.remote import push_branches
from git_scripts.git.topology import (
    TopologyAnalyzer,
    get_parent_branch,
    sort_branches_bottom_to_top,
)
from git_scripts.ui import UI


def _get_branch_commit_id(
    repo: pygit2.Repository, branch: str
) -> pygit2.Oid | None:
    try:
        return repo.revparse_single(branch).id
    except (KeyError, ValueError, pygit2.GitError):
        return None


def _walk_up_ancestors(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    branch_to_commit: dict[str, pygit2.Oid],
    stack: set[str],
) -> None:
    """Traverses ancestors up to target, adding branches to stack."""
    target_commit_id = branch_to_commit.get(target)
    curr_branch = current_branch
    while True:
        parent = get_parent_branch(repo, curr_branch, pool)
        if not parent or parent == target:
            break
        parent_cid = branch_to_commit.get(parent)
        if parent_cid == target_commit_id:
            break
        colocated_parents = {
            b for b, cid in branch_to_commit.items() if cid == parent_cid
        }
        stack.update(colocated_parents)
        curr_branch = parent


def _walk_down_descendants(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    branch_to_commit: dict[str, pygit2.Oid],
    stack: set[str],
    ui: UI,
) -> bool:
    """Traverses descendants down to tip, checking for forks."""
    curr_branch = current_branch
    while True:
        curr_cid = branch_to_commit.get(curr_branch)
        children = []
        for b in branch_to_commit:
            if b in stack or b == target:
                continue
            parent = get_parent_branch(repo, b, pool)
            if parent and branch_to_commit.get(parent) == curr_cid:
                children.append(b)

        if not children:
            break

        distinct_child_commits = {
            branch_to_commit[b] for b in children if b in branch_to_commit
        }
        if len(distinct_child_commits) > 1:
            ui.print(
                f"[red]❌  Fork detected downstream at branch '{curr_branch}'."
                "[/red]\n"
                f"    Children: {', '.join(sorted(children))}\n"
                "    Cannot determine a single linear stack to rebase.\n"
                "    Please checkout the specific tip branch you want "
                "to rebase."
            )
            return False

        stack.update(children)
        curr_branch = children[0]

    return True


def _get_linear_stack(
    repo: pygit2.Repository,
    current_branch: str,
    target: str,
    pool: set[str],
    ui: UI,
) -> set[str] | None:
    """Finds the full linear stack containing current_branch within pool."""
    current_commit_id = _get_branch_commit_id(repo, current_branch)
    if not current_commit_id:
        return None

    branch_to_commit = {
        b: cid
        for b in pool
        if (cid := _get_branch_commit_id(repo, b)) is not None
    }

    # Start with all branches co-located with current_branch
    stack = {
        b for b, cid in branch_to_commit.items() if cid == current_commit_id
    }

    if current_branch != target:
        _walk_up_ancestors(
            repo, current_branch, target, pool, branch_to_commit, stack
        )

    if not _walk_down_descendants(
        repo, current_branch, target, pool, branch_to_commit, stack, ui
    ):
        return None

    stack.discard(target)
    return stack


def execute_rebase_stack(
    repo_path: str = ".",
    target: str = "main",
    all_worktrees: bool = False,
    auto_delete: bool = False,
    ui: UI | None = None,
) -> bool:
    """Executes the rebase-stack command to rebase the current linear stack."""
    if ui is None:
        ui = UI()

    repo = pygit2.Repository(repo_path)

    if repo.head_is_detached:
        ui.print("[red]❌  Cannot rebase stack from detached HEAD.[/red]")
        return False

    current_branch = repo.head.shorthand

    if current_branch == target:
        ui.print(
            f"[yellow]Current branch is target branch '{target}'. "
            "Nothing to rebase.[/yellow]"
        )
        return True

    ui.print(f"[dim]🔍  Analyzing stack for '{current_branch}'...[/dim]")

    pool = {
        ref[len("refs/heads/") :]
        for ref in repo.references
        if ref.startswith("refs/heads/")
    }
    pool.add(target)

    stack = _get_linear_stack(repo, current_branch, target, pool, ui)
    if stack is None:
        return False

    if not stack:
        ui.print(
            f"  [yellow]No branches found in stack between '{current_branch}' "
            f"and target '{target}'.[/yellow]"
        )
        return True

    parent_map = {b: get_parent_branch(repo, b, stack) for b in stack}
    ordered_stack = sort_branches_bottom_to_top(stack, parent_map)
    ordered_stack = [b for b in ordered_stack if b != target]

    if not ui_update_target(repo_path, target, ui):
        try:
            run_cmd(["git", "checkout", current_branch], cwd=repo_path)
        except GitExecutionError:
            pass
        return False

    analyzer = TopologyAnalyzer(repo_path, ordered_stack)
    ui.print(f"  [bold]Found {len(analyzer.tips)} stack tips.[/bold]")

    start_time = time.time()
    analyzer.analyze_obsolescence(
        target,
        progress_callback=lambda msg: ui.print(f"  [dim]⏳ {msg}[/dim]"),
    )
    elapsed = time.time() - start_time
    ui.print(f"  [dim]⏱️  Topology analysis completed in {elapsed:.2f}s[/dim]")

    if all_worktrees:
        ui.print(
            "[dim]🔄  Detaching worktrees for cross-worktree rebase...[/dim]"
        )

    branch_pool = set(ordered_stack)
    batch_result, completed = rebase_loop(
        analyzer,
        repo_path,
        "",
        target,
        all_worktrees,
        ui,
        branch_pool,
    )
    if not completed:
        return False

    print_batch_summary(ui, batch_result)

    prompt_and_delete_merged(batch_result, auto_delete, ui, repo_path)

    try:
        run_cmd(["git", "checkout", current_branch], cwd=repo_path)
    except GitExecutionError:
        pass

    if batch_result.branches_to_keep:
        branches_list = list(batch_result.branches_to_keep)
        ui.print()
        ui.print(
            Panel(
                "\n".join(f"  - [yellow]{b}[/yellow]" for b in branches_list),
                title=(
                    f"[bold cyan]Local branches updated "
                    f"({len(batch_result.branches_to_keep)})[/bold cyan]"
                ),
                border_style="cyan",
                expand=False,
            )
        )
        resolved_branches = resolve_branches_to_push(
            branches=branches_list,
            ui=ui,
            prompt_title=(
                f"Push {len(batch_result.branches_to_keep)} updated "
                "branches to origin?"
            ),
        )
        if resolved_branches:
            push_branches(
                branches=resolved_branches,
                options=["--force-with-lease"],
                repo_path=repo_path,
            )

    return len(batch_result.failed_log) == 0
