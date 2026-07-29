"""Data models for git-scripts."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class StackAnalysisResult(BaseModel):
    """Result of analyzing a stack tip for rebasing."""

    model_config = ConfigDict(frozen=True)

    branch: str
    action: Literal[
        "skip",
        "rebase_onto_sync",
        "rebase_onto_cut",
        "rebase_standard",
        "error",
    ]
    reason: Optional[str] = None
    sync_branch: Optional[str] = None
    sync_old_hash: Optional[str] = None
    sync_new_hash: Optional[str] = None
    cut_point: Optional[str] = None
