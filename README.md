# Git Stack Utilities

A collection of scripts to wrangle branches, especially in a [stacked-diff](https://newsletter.pragmaticengineer.com/p/stacked-diffs) context in repos where the main branch keeps updating.

These scripts handle "obsolete" commits, merged commits, and branching histories relatively intelligently. Stack structure and branching are preserved, and any rebase issues are flagged and gracefully aborted for that stack.

**Requirements:** Git 2.38+ (relies on `rebase --update-refs`).

## Setup

Add to your shell rc file (`.zshrc` / `.bashrc`):
```bash
source git_bash_functions.sh
```

## Usage

| Function | Description |
| :--- | :--- |
| **`git_rebase_prefix <prefix> [base]`** | **Batch Update.** Rebases all stacks matching `prefix` onto `base` (default: `main`). Preserves topology; skips commits already squashed upstream. |
| **`git_evolve`** | **Rescue Orphans.** Run immediately after `git commit --amend` to rebase child branches onto the new HEAD automatically. |
| **`git_push_prefix <prefix> [opts]`** | **Batch Push.** Pushes all branches matching `prefix`. Passes extra args (e.g., `--force-with-lease`) to git. |
| **`git_prune_remote_prefix <prefix>`** | **Remote Cleanup.** Deletes remote branches that are fully merged or squash-merged into `main`. |
| **`git_prune_local_branches`** | **Local Cleanup.** Deletes local branches whose remote tracking branches are gone. |