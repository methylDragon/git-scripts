"""Data models for Git operations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


class ScriptAbortError(Exception):
    """Exception raised when the user explicitly aborts during a conflict."""

    pass


class RebaseStatus(Enum):
    """The execution result of a rebase operation."""

    # Rebase completed successfully without manual intervention.
    SUCCESS = "success"

    # Rebase halted due to a merge conflict.
    CONFLICT = "conflict"

    # Rebase failed catastrophically (e.g., network error, bad state).
    ERROR = "error"


class UpdateTargetResult(Enum):
    """The result of updating a target branch."""

    SUCCESS = "success"
    FETCHED_ONLY = "fetched_only"
    LOCAL_ONLY = "local_only"


@dataclass(frozen=True)
class BranchRebasePlan:
    """Rebase action blueprint for a single branch based on topology."""

    # The local branch name being analyzed.
    branch: str

    # The computed rebase action to apply.
    action: RebaseAction

    # Optional explanation for the chosen action (e.g., 'Fully merged').
    reason: str | None = None

    # The parent branch this branch is stacked on (if any).
    sync_branch: str | None = None

    # The hash the sync_branch pointed to before it was moved.
    sync_old_hash: str | None = None

    # The hash the sync_branch currently points to.
    sync_new_hash: str | None = None

    # The commit hash to cut from if the base was squashed/rebased.
    cut_point: str | None = None


@dataclass(frozen=True)
class BatchRebaseConfig:
    """Static configuration for a batch rebase operation."""

    repo_path: str
    prefix: str
    target: str
    all_worktrees: bool
    analyzer: Any
    branch_pool: set[str]


@dataclass
class SingleBranchResult:
    """Aggregatable result of a single branch operation."""

    success_log: list[str] = field(default_factory=list)
    skipped_log: list[str] = field(default_factory=list)
    failed_log: list[str] = field(default_factory=list)
    branches_to_delete: set[str] = field(default_factory=set)
    branches_to_keep: set[str] = field(default_factory=set)

    def aggregate(self, other: "SingleBranchResult") -> None:
        """Aggregates another result into this one."""
        self.success_log.extend(other.success_log)
        self.skipped_log.extend(other.skipped_log)
        self.failed_log.extend(other.failed_log)
        self.branches_to_delete.update(other.branches_to_delete)
        self.branches_to_keep.update(other.branches_to_keep)


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
    cut_point: str | None = None


@dataclass(frozen=True)
class WorktreeState:
    """State tracking for detached branches across worktrees."""

    # Map of worktree paths to branch names that were detached.
    detached_map: dict[str, str]

    # Branches that could not be detached (e.g., due to active merges).
    failed_branches: set[str]
