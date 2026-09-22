"""Data models and configuration schemas for git-gk-optimize."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_BUNDLED_CONFIG_YAML = Path(__file__).resolve().parent / "config.yaml"
_BUNDLED_DEFAULTS: dict = (
    yaml.safe_load(_BUNDLED_CONFIG_YAML.read_text(encoding="utf-8")) or {}
    if _BUNDLED_CONFIG_YAML.is_file()
    else {}
)
_DEFAULT_TAGS: dict = _BUNDLED_DEFAULTS.get("tags", {})
_DEFAULT_WATCHER: dict = _BUNDLED_DEFAULTS.get("watcher", {})


class GkExpectMode(str, Enum):
    """Expected installation state for verification."""

    INSTALLED = "installed"
    UNINSTALLED = "uninstalled"


class GkTagConfig(BaseModel):
    """Config for per-pattern tag retention counts and blocked patterns."""

    keep_other_tags: bool = Field(
        default=bool(_DEFAULT_TAGS.get("keep_other_tags", True))
    )
    prune_interval_hours: float = Field(
        default=float(_DEFAULT_TAGS.get("prune_interval_hours", 12.0))
    )
    keep_recent_by_pattern: dict[str, int] = Field(
        default_factory=lambda: dict(
            _DEFAULT_TAGS.get("keep_recent_by_pattern", {})
        )
    )
    blocked_fetch_patterns: list[str] = Field(
        default_factory=lambda: list(
            _DEFAULT_TAGS.get("blocked_fetch_patterns", [])
        )
    )


class GkWatcherConfig(BaseModel):
    """Config for NSFW (Node Sentinel File Watcher) symlink/dir filtering."""

    ignored_dirs: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_WATCHER.get("ignored_dirs", []))
    )


class GkOptimizerConfig(BaseModel):
    """Top-level install-time YAML configuration for git-gk-optimize."""

    tags: GkTagConfig = Field(default_factory=GkTagConfig)
    watcher: GkWatcherConfig = Field(default_factory=GkWatcherConfig)


@dataclass(frozen=True)
class GkOptimizeResult:  # pylint: disable=too-many-instance-attributes
    """Result of executing an install or uninstall operation."""

    success: bool
    repo_root: str
    common_git_dir: str
    pruned_tags_count: int
    kept_tags_count: int
    shim_so_path: str
    desktop_entry_path: str
    details: list[str]


@dataclass(frozen=True)
class GkVerifyResult:
    """Result of verifying installed or uninstalled optimizer state."""

    passed: bool
    checks: dict[str, bool]
    failures: list[str]
