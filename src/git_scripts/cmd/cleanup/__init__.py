"""Cleanup command execution modules for local and remote branches."""

from git_scripts.cmd.cleanup.prune_local import execute_prune_local
from git_scripts.cmd.cleanup.prune_remote_prefix import (
    execute_prune_remote_prefix,
)

__all__ = [
    "execute_prune_local",
    "execute_prune_remote_prefix",
]
