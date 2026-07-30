"""Data models for Git operations."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RebaseAction(Enum):
    """The calculated operation to apply to a branch during a rebase."""

    # Branch is fully merged; skip rebasing and mark for deletion.
    SKIP = "skip"

    # Parent branch was rebased; rebase this branch onto the new parent hash.
    REBASE_ONTO_SYNC = "rebase_onto_sync"

    # Base was squashed/merged; cut the branch at the common ancestor.
    REBASE_ONTO_CUT = "rebase_onto_cut"

    # Standard rebase onto the target branch.
    REBASE_STANDARD = "rebase_standard"

    # Failed to determine a valid rebase strategy.
    ERROR = "error"


@dataclass(frozen=True)
class BranchRebaseResult:
    """Rebase action strategy for a single branch based on topology."""

    # The local branch name being analyzed.
    branch: str

    # The computed rebase strategy to apply.
    action: RebaseAction

    # Optional explanation for the chosen action (e.g., 'Fully merged').
    reason: Optional[str] = None

    # The parent branch this branch is stacked on (if any).
    sync_branch: Optional[str] = None

    # The hash the sync_branch pointed to before it was moved.
    sync_old_hash: Optional[str] = None

    # The hash the sync_branch currently points to.
    sync_new_hash: Optional[str] = None

    # The commit hash to cut from if the base was squashed/rebased.
    cut_point: Optional[str] = None


@dataclass(frozen=True)
class RemotePruneResult:
    """Result of analyzing remote branches for pruning."""

    # Branches that have been fully merged into the target.
    obsolete_branches: list[str]

    # Branches not merged, but lacking a local tracking branch.
    unmerged_no_local_branches: list[str]


@dataclass(frozen=True)
class TopologyAnalysisResult:
    """Analysis result for a branch tip against the target branch."""

    # True if all commits in this branch have been merged into the target.
    is_obsolete: bool

    # The latest common ancestor commit if the branch needs cutting.
    cut_point: Optional[str] = None


@dataclass(frozen=True)
class WorktreeState:
    """State tracking for detached branches across worktrees."""

    # Map of worktree paths to branch names that were detached.
    detached_map: dict[str, str]

    # Branches that could not be detached (e.g., due to active merges).
    failed_branches: set[str]
