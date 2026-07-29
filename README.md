# Git Stack Utilities

[![CI](https://github.com/methylDragon/git-scripts/actions/workflows/main.yml/badge.svg)](https://github.com/methylDragon/git-scripts/actions/workflows/main.yml)
[![Coverage Status](https://coveralls.io/repos/github/methylDragon/git-scripts/badge.svg?branch=main)](https://coveralls.io/github/methylDragon/git-scripts?branch=main)

A collection of scripts to wrangle branches, especially in a [stacked-diff](https://newsletter.pragmaticengineer.com/p/stacked-diffs) context in repos where the main branch keeps updating.

These scripts handle "obsolete" commits, merged commits, and branching histories relatively intelligently. Stack structure and branching are preserved, and any rebase issues are flagged and gracefully aborted for that stack.

## Setup

1. **Install:** Run the automated installer, which clones the repo. *(It will automatically install [`pixi`](https://pixi.sh/) if you don't already have it.)*

    ```bash
    curl -sSL https://raw.githubusercontent.com/methylDragon/git-scripts/main/install.sh | bash
    ```

   **Note: Local Installation**

   If you have a local clone of this repository and want to install from it (useful for development), you can run this instead:

   ```bash
   ./install.sh --local
   ```

This sets up the environment and creates symlinks to `~/.local/bin` directly from your local clone.

1. **Verify:** Ensure `~/.local/bin` is in your system's `$PATH`.

The installer creates native Git subcommands! Because the executables are prefixed with `git-` and placed in your `PATH`, Git automatically recognizes them.

To update the scripts later, simply run:

```bash
git-scripts-update
```

## Usage

You can invoke these scripts just like native Git commands:

| Command | Description |
| :--- | :--- |
| **`git rebase-prefix <prefix> [target] [--all-worktrees] [--auto-delete] [--obsolete-search-depth <int>]`** | **Batch Update.** Rebases all stacks matching `prefix` onto `target` (default: `main`). Preserves topology; skips commits already squashed upstream. |
| **`git evolve [old_hash]`** | **Rescue Orphans.** Run immediately after `git commit --amend` to rebase child branches onto the new HEAD automatically. Calculates from reflog if `old_hash` is omitted. |
| **`git push-prefix <prefix> [opts]`** | **Batch Push.** Pushes all branches matching `prefix`. Passes extra args (e.g., `--force-with-lease`) to git. |
| **`git prune-remote-prefix <prefix> [target] [-n/--dry-run] [--obsolete-search-depth <int>]`** | **Remote Cleanup.** Deletes remote branches that are fully merged or squash-merged into `target` (default: `main`). |
| **`git prune-local-branches [-n/--dry-run]`** | **Local Cleanup.** Deletes local branches whose remote tracking branches are gone. |

> **Note:** All commands support `--plain` (disables rich UI formatting) and `-y/--yes` (bypasses confirmation prompts).

### Working with Worktrees

If you heavily utilize `git worktree` for stacked PRs, you might run into Git lock errors when trying to update a branch that is currently checked out in another worktree.

The `git rebase-prefix` command accepts an `--all-worktrees` flag, while `git evolve` handles worktrees **automatically**. When active, the tool detects if any branches in your stack are checked out in other worktrees. It safely detaches those worktrees, performs the complex topology rebases, and then cleanly re-checks out the updated branches in their original worktrees.

## Testing

This repository uses `pytest` for unit testing the Python logic and `absltest` for parameterization. We also use `pytest-xdist` to speed up tests by running them in parallel.

1. **Install dependencies:**
   `pixi install` will automatically handle all required dependencies.

1. **Run tests:**

   ```bash
   pixi run test
   ```

## Development

If you'd like to contribute to this project, we enforce formatting (`ruff-format`) and linting (`ruff`) for Python files, as well as `markdownlint` and shell linting/formatting via `pre-commit`.

1. **Install dependencies & hooks:**
   Everything is managed via `pixi`. Remember to run `pixi install` if you cloned this repository.

   ```bash
   pixi run setup
   ```

   Now, every time you commit, it will automatically check your scripts.

1. **Run manually:**
   You can trigger formatting and linting across all files without committing by running:

   ```bash
   pixi run pre-commit
   ```
