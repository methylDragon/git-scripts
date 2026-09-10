"""Domain logic for planning rebases based on topological drift."""

from git_scripts.git.rebase import (
    rebase_stack,
    rebase_stack_onto,
)
from git_scripts.git.topology import TopologyAnalyzer
from git_scripts.models import BranchRebasePlan, RebaseAction, RebaseStatus


def create_rebase_plan(
    analyzer: TopologyAnalyzer, branch: str
) -> BranchRebasePlan:
    """Analyzes a branch's topology to determine its optimal rebase plan."""
    analysis_data = analyzer.get_analysis(branch)
    if analysis_data.is_obsolete:
        return BranchRebasePlan(
            branch=branch, action=RebaseAction.SKIP, reason="Fully merged"
        )

    sync_point = analyzer.get_sync_point(branch)
    if sync_point:
        return BranchRebasePlan(
            branch=branch,
            action=RebaseAction.REBASE_ONTO_SYNC,
            sync_branch=sync_point[0],
            sync_old_hash=sync_point[1],
            sync_new_hash=sync_point[2],
        )

    cut_point = analysis_data.cut_point
    if cut_point:
        return BranchRebasePlan(
            branch=branch,
            action=RebaseAction.REBASE_ONTO_CUT,
            cut_point=cut_point,
        )

    return BranchRebasePlan(branch=branch, action=RebaseAction.REBASE_STANDARD)


def execute_rebase_plan(
    plan: BranchRebasePlan, repo_path: str, target: str
) -> RebaseStatus:
    """Executes a pre-computed rebase plan by dispatching pure git commands."""
    match plan.action:
        case RebaseAction.REBASE_ONTO_SYNC if (
            plan.sync_new_hash and plan.sync_old_hash
        ):
            return rebase_stack_onto(
                new_base_commit_hash=plan.sync_new_hash,
                old_base_commit_hash=plan.sync_old_hash,
                tip_branch=plan.branch,
                repo_path=repo_path,
            )
        case RebaseAction.REBASE_ONTO_CUT if plan.cut_point:
            return rebase_stack_onto(
                new_base_commit_hash=target,
                old_base_commit_hash=plan.cut_point,
                tip_branch=plan.branch,
                repo_path=repo_path,
            )
        case RebaseAction.REBASE_STANDARD:
            return rebase_stack(
                new_base_branch=target,
                tip_branch=plan.branch,
                repo_path=repo_path,
            )
        case _:
            return RebaseStatus.ERROR
