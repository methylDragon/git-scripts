"""Business logic for pruning local branches."""

from rich.panel import Panel

from git_scripts.git.writes import GitExecutionError, run_cmd
from git_scripts.ui import UI


def _get_worktree_branches(repo_path: str) -> set[str]:
    """Retrieves a set of local branches currently checked out in worktrees."""
    try:
        worktrees_out = run_cmd(
            ["git", "worktree", "list", "--porcelain"], cwd=repo_path
        )
        worktree_branches = set()
        for line in worktrees_out.splitlines():
            if line.startswith("branch refs/heads/"):
                worktree_branches.add(line[len("branch refs/heads/") :])
        return worktree_branches
    except GitExecutionError:
        return set()


def _get_gone_branches(
    repo_path: str, worktree_branches: set[str]
) -> list[str]:
    """Finds local branches whose upstream tracking branches are gone."""
    try:
        branch_vv_out = run_cmd(["git", "branch", "-vv"], cwd=repo_path)
    except GitExecutionError:
        return []

    branches_to_prune = []
    for line in branch_vv_out.splitlines():
        if ": gone]" in line:
            parts = line.strip().split()
            branch = parts[1] if parts[0] in ("*", "+") else parts[0]
            if branch not in worktree_branches:
                branches_to_prune.append(branch)
    return branches_to_prune


def execute_prune_local(
    repo_path: str, dry_run: bool = False, ui=None
) -> bool:
    """Executes the pruning of fully merged local branches."""
    if ui is None:
        ui = UI()

    if dry_run:
        ui.print("Running git-prune-local-branches in dry-run mode...")

    ui.print("[dim]🔄  Fetching origin --prune...[/dim]")
    try:
        run_cmd(["git", "fetch", "-p"], cwd=repo_path)
    except GitExecutionError:
        pass

    worktree_branches = _get_worktree_branches(repo_path)
    branches_to_prune = _get_gone_branches(repo_path, worktree_branches)

    if not branches_to_prune:
        ui.print("✅  No orphaned branches to prune.")
        return True

    branch_list = "\n".join(f"  - [cyan]{b}[/cyan]" for b in branches_to_prune)
    ui.print(
        Panel(
            branch_list,
            title=(
                f"[bold yellow]Found {len(branches_to_prune)} "
                "orphaned local branches[/bold yellow]"
            ),
            border_style="yellow",
            expand=False,
        )
    )

    if dry_run:
        ui.print("\n📦  [Dry Run] No branches would be deleted.")
        return True

    if not ui.auto_yes:
        action = ui.ask_choice(
            f"❓  Delete the {len(branches_to_prune)} "
            "orphaned local branches?",
            choices=["Skip all", "Select which to delete", "Delete all"],
            default="Skip all",
        )

        if action == "Delete all":
            pass
        elif action == "Select which to delete":
            branches_to_prune = ui.ask_checkbox(
                "Select orphaned local branches to delete:",
                choices=branches_to_prune,
            )
        else:
            branches_to_prune = []

    if not branches_to_prune:
        return True

    ui.print("\n🗑️  Pruning branches...")
    try:
        cmd = ["git", "branch", "-D"] + branches_to_prune
        out = run_cmd(cmd, cwd=repo_path)
        ui.print(out)
        return True
    except GitExecutionError as e:
        ui.print(f"[red]Failed to prune branches: {e}[/red]")
        return False
