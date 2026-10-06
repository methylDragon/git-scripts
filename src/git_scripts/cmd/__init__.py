"""Core command execution modules for the CLI."""

from git_scripts.cmd.cleanup import (
    execute_prune_local,
    execute_prune_remote_prefix,
)
from git_scripts.cmd.evolve import execute_evolve
from git_scripts.cmd.gh.pr_aligner import (
    execute_align_pr_bases_and_sync_stacks,
)
from git_scripts.cmd.push import execute_push_prefix, execute_push_stack
from git_scripts.cmd.rebase import execute_rebase_prefix, execute_rebase_stack

__all__ = [
    "execute_align_pr_bases_and_sync_stacks",
    "execute_evolve",
    "execute_prune_local",
    "execute_prune_remote_prefix",
    "execute_push_prefix",
    "execute_push_stack",
    "execute_rebase_prefix",
    "execute_rebase_stack",
]
