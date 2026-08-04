"""Core logic for the git-push-stack command."""

import pygit2
from rich.panel import Panel

from git_scripts.git.topology import (
    get_parent_branch,
    sort_branches_bottom_to_top,
)
from git_scripts.git.writes import GitExecutionError, push_branches, run_cmd
from git_scripts.ui import UI


def _get_out_of_sync_branches_in_stack(
    repo: pygit2.Repository, stack_branches: list[str]
) -> tuple[list[str], int]:
    """Finds branches in the stack that differ from remote."""
    branches_to_push = []
    up_to_date_count = 0

    for short_name in stack_branches:
        ref = f"refs/heads/{short_name}"
        try:
            local_commit = repo.revparse_single(ref)
            try:
                remote_commit = repo.revparse_single(
                    f"refs/remotes/origin/{short_name}"
                )
                if local_commit.id != remote_commit.id:
                    branches_to_push.append(short_name)
                else:
                    up_to_date_count += 1
            except KeyError:
                branches_to_push.append(short_name)
        except KeyError:
            continue

    return branches_to_push, up_to_date_count


def _get_linear_stack(
    repo, current_branch: str, target: str, pool: set[str], ui
) -> set[str] | None:
    stack = {current_branch}

    if current_branch != target:
        # Walk up to ancestors
        curr = current_branch
        while True:
            parent = get_parent_branch(repo, curr, pool)
            if not parent:
                break
            if parent == target:
                break
            stack.add(parent)
            curr = parent

    # Walk down to descendants
    curr = current_branch
    while True:
        children = [
            b
            for b in pool
            if b not in stack and get_parent_branch(repo, b, pool) == curr
        ]

        if not children:
            break

        if len(children) > 1:
            ui.print(
                f"[red]❌  Fork detected downstream at branch '{curr}'."
                "[/red]\n"
                f"    Children: {', '.join(children)}\n"
                "    Cannot determine a single linear stack to push.\n"
                "    Please checkout the specific tip branch you want to push."
            )
            return None

        child = children[0]
        stack.add(child)
        curr = child

    stack.discard(target)
    return stack


def execute_push_stack(
    repo_path: str,
    target: str = "main",
    push_opts: list[str] | None = None,
    ui=None,
) -> bool:
    """Pushes out-of-sync local branches in the current stack to the remote."""
    if ui is None:
        ui = UI()

    if push_opts is None:
        push_opts = []

    repo = pygit2.Repository(repo_path)

    if repo.head_is_detached:
        ui.print("[red]❌  Cannot push stack from detached HEAD.[/red]")
        return False

    current_branch = repo.head.shorthand

    ui.print("[cyan]🔄  Fetching origin...[/cyan]")
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_path)
    except GitExecutionError:
        pass

    ui.print(f"[cyan]🔍  Analyzing stack for '{current_branch}'...[/cyan]")

    pool = {
        ref[len("refs/heads/") :]
        for ref in repo.references
        if ref.startswith("refs/heads/")
    }

    # Stop at `target`. Target MUST be in pool for `get_parent_branch` to
    # find it. `target` is not added to `stack`.
    pool.add(target)

    # Determine the linear stack
    stack = _get_linear_stack(repo, current_branch, target, pool, ui)
    if stack is None:
        return False

    if not stack or (len(stack) == 1 and list(stack)[0] == target):
        ui.print(
            f"    No branches found in stack between '{current_branch}' "
            f"and target '{target}'."
        )
        return True

    parent_map = {b: get_parent_branch(repo, b, stack) for b in stack}
    ordered_stack = sort_branches_bottom_to_top(stack, parent_map)
    ordered_stack = [b for b in ordered_stack if b != target]

    branches_to_push, up_to_date_count = _get_out_of_sync_branches_in_stack(
        repo, ordered_stack
    )

    if not branches_to_push:
        if up_to_date_count == 0:
            ui.print("    No matching branches found.")
        else:
            ui.print(
                f"✅  All branches in stack ({up_to_date_count}) "
                "are already up-to-date with origin."
            )
        return True

    branch_list = "\n".join(f"  - [cyan]{b}[/cyan]" for b in branches_to_push)
    ui.print(
        Panel(
            branch_list,
            title=(
                f"[bold cyan]Found {len(branches_to_push)} branches to "
                f"push[/bold cyan] [dim](Skipped {up_to_date_count} "
                "up-to-date)[/dim]"
            ),
            border_style="cyan",
            expand=False,
        )
    )

    if not ui.auto_yes:
        action = ui.ask_choice(
            f"❓  Push {len(branches_to_push)} branches in stack to origin?",
            choices=["Push all", "Select which to push", "Skip all"],
            default="Push all",
        )
        match action:
            case "Skip all":
                ui.print("❌  Operation cancelled.")
                return True
            case "Select which to push":
                branches_to_push = ui.ask_checkbox(
                    "Select branches to push:", choices=branches_to_push
                )

    if not branches_to_push:
        ui.print("❌  Operation cancelled.")
        return True

    opts_str = " ".join(push_opts) or "(none)"
    ui.print(f"\n🚀  Pushing to origin (Options: {opts_str})...")
    if push_branches(branches_to_push, push_opts, repo_path=repo_path):
        ui.print("\n✅  Batch push complete.")
        return True
    else:
        ui.print("\n[red]❌  Push failed.[/red]")
        return False
