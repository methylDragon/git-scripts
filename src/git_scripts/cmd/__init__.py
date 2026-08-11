"""Core command execution modules for the CLI."""

from git_scripts.cmd.evolve import execute_evolve
from git_scripts.cmd.prune_local import execute_prune_local
from git_scripts.cmd.prune_remote_prefix import execute_prune_remote_prefix
from git_scripts.cmd.push_prefix import execute_push_prefix
from git_scripts.cmd.rebase_prefix import execute_rebase_prefix

__all__ = [
    "execute_evolve",
    "execute_prune_local",
    "execute_prune_remote_prefix",
    "execute_push_prefix",
    "execute_rebase_prefix",
]
