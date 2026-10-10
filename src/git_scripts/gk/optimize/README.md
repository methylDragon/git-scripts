# GitKraken Worktree Optimizer (`git gk`)

## Overview

GitKraken Desktop on Linux degrades on large repositories and linked Git worktrees (`git worktree add`): its file watcher follows symlinks into build caches, thousands of automated CI tags slow down background fetches and tab switches, switching back to a recently opened tab blocks on `"Opening repo"` while waiting for a full 9-step refresh, commit detail panels stutter on open, and terminal Git commands inside linked worktrees do not refresh the commit graph.

`git gk` (legacy alias: `git-gk-optimize`) fixes these bottlenecks out-of-tree (`~/.config/gitkraken-optimizer/`) without modifying `/usr/share/gitkraken/` on disk, so optimizations survive system package updates and can be cleanly reverted at any time.

## Architecture

### Install and Uninstall (`git gk`)

- [`shim_builder.py`](shim_builder.py) and [`gitkraken_launcher.py`](gitkraken_launcher.py): Builds `libgk_preload_shim.so` with CMake, verifies that the installed `/usr/share/gitkraken/resources/app.asar` matches the expected in-memory patch targets (printing version and remediation hints if a GitKraken update shifts them), and writes `gitkraken-launcher`, the `/bin/sh` fast-path `gitkraken-git` wrapper (plus `git_wrapper.py`), `watched_repos.json`, and `~/.local/share/applications/gitkraken.desktop`.
- [`config_loader.py`](config_loader.py) and [`models.py`](models.py): Loads [`config.yaml`](config.yaml) and symlinks it into `~/.config/gitkraken-optimizer/` and `<common-git-dir>/gk-optimizer/`.
- [`tag_pruner.py`](tag_pruner.py): Backs up pre-existing tag and remote branch SHAs (`pre_install_refs.json`) and trims CI tag and `refs/remotes/origin/*` namespaces to the configured retention window while protecting checked-out worktrees, local branches, and tracked upstreams.
- [`state_manager.py`](state_manager.py): Configures negative tag fetch refspecs and NodeGit-safe repository performance settings (`core.commitGraph`, `core.untrackedCache`, `fetch.writeCommitGraph`, `fetch.prune`) in `.git/config`, trims bloated `remoteHeadCollectionByRemoteName` and `tags` visibility maps in GitKraken `repoSettings` files, and restores original state via Compare-And-Swap on `uninstall`.

### Runtime (`gitkraken-launcher`)

`gitkraken.desktop` launches `/usr/share/gitkraken/gitkraken` through `~/.config/gitkraken-optimizer/gitkraken-launcher`, which exports `LD_PRELOAD=libgk_preload_shim.so` and starts `watch-daemon`:

- [`csrc/gk_preload_shim.c`](csrc/gk_preload_shim.c) (`libgk_preload_shim.so`): `LD_PRELOAD` library that prunes `nsfw.node` directory traversal, patches `app.asar` UI transition rules and cached tab-switch refresh behavior in memory, and automatically strips itself from `LD_PRELOAD` in child shells and subprocesses.
- [`git_wrapper.py`](git_wrapper.py) (`gitkraken-git`): `/bin/sh` fast-path wrapper for `selectedGitPath` that unsets `LD_PRELOAD` and `exec`s `/usr/bin/git` directly on local commands (`status`, `rev-list`, `for-each-ref`), delegating only `fetch` and `ls-remote` to the stdlib Python filter.
- [`worktree_watcher.py`](worktree_watcher.py) (`watch-daemon`): Session daemon bound to GitKraken's PID that refreshes linked worktrees on ref changes and re-trims excess CI tags and remote-tracking branches after fetches.

## Usage

```bash
# Install optimizations for a repository and its linked worktrees
git gk install ~/path/to/repo --close-gitkraken

# Override the tag retention count or pass a custom YAML configuration
git gk install ~/path/to/repo --config custom.yaml --keep-recent-tags 5

# Verify installation state (exits 0 if all checks pass)
git gk verify ~/path/to/repo --expect installed

# Restore original repository refs and user settings
git gk uninstall ~/path/to/repo --close-gitkraken
```

## Issues and Solutions

### Symlink and Build Directory Crawling

GitKraken's file watcher (`nsfw.node`) recursively walks the working tree with `stat64`, which follows symlinks into external build caches (`bazel-*`) and large dependency folders (`node_modules`, `.venv`, `.pixi`, `target`), registering hundreds of thousands of `inotify` watches and stalling tab switches.

`libgk_preload_shim.so` intercepts `stat` calls originating from `nsfw.node` (`dladdr` check) so watcher behavior matches how Git tracks files:

- **Symlinked repository and submodule roots are still followed**: If a symlink itself contains `.git` (for example, opening a repository via a symlinked directory path), the shim resolves it as a directory so GitKraken watches the repository normally.
- **Git-tracked symlinks are still watched for changes without crawling targets**: Git stores working-tree symlinks as mode `120000` pointer entries (`lstat`) rather than indexing files inside the target directory. Returning `S_ISLNK` stops `nsfw.node` from recursing into external symlink targets (such as `bazel-*` output caches), while the parent directory's `inotify` watch still detects whenever a symlink itself is created, deleted, or retargeted.
- **Configured directories are still skipped**: Real directories matching `watcher.ignored_dirs` in [`config.yaml`](config.yaml) are masked from `nsfw.node` directory recursion, while normal filesystem calls from `libgit2`, `git`, and the rest of GitKraken remain untouched.

### Slow `"Opening repo"` Overlay and Background Refresh on Tab Switches

GitKraken caches the Redux store of up to 10 recently opened repositories (`sessionRepoReduxStoreCache`) and restores that snapshot immediately on tab switch (`CachedRepoReduxStoreLoaded`). However, the cached branch of `openRepoSaga` still calls `refreshRepo` with `blocking: true` while `_updateTabsSaga` holds `tabIdDisplayingLoadyspin` active, locking the `"Opening repo"` overlay on screen until all 9 refresh steps (`repoSettings` JSON parsing, `git status`, `git rev-list`, and ref enumeration) finish.

To make both cached tab switches and background refreshes fast:

- **Non-blocking cached tab switches in memory**: When Electron reads `app.asar`, `libgk_preload_shim.so` rewrites `blocking:!0,callSource:"RepoSagas.openRepo (usingReduxCache)"` to `blocking:!1,callSource:"RepoSagas.openRepo (usingReduxCache)"` in RAM. Switching to a previously loaded tab immediately renders the cached commit graph while the refresh completes in the background. During `git gk install` and `git gk verify`, `verify_asar_compatibility` checks `app.asar` to confirm all in-memory patch targets match the installed GitKraken version (`12.4.x`, tested on `v12.4.0`) and prints remediation hints if an update changes any target string.
- **Fast-path `/bin/sh` Git wrapper**: `gitkraken-git` uses a `/bin/sh` front door that unsets `LD_PRELOAD` and `exec`s `/usr/bin/git` directly for local Git commands (`status`, `rev-list`, `for-each-ref`, `config`), starting Python (`git_wrapper.py`) only when `fetch` or `ls-remote` appears in the arguments.
- **Commit-graph and untracked-cache acceleration**: On install, the optimizer generates `.git/objects/info/commit-graph` (`git commit-graph write --reachable`) and sets `core.commitGraph = true`, `core.untrackedCache = true`, `fetch.writeCommitGraph = true`, and `fetch.prune = true` in `.git/config` so `git rev-list` and `git status` skip redundant object decompression and directory `lstat` walks while remaining compatible with GitKraken's bundled `@axosoft/nodegit@0.28.0-alpha.38`.

### Commit Detail Panel Animation Lag

Selecting a commit opens the right-hand detail panel with a `250ms` flexbox width transition. Because the commit graph resizes on every animation frame, the detail panel noticeably stutters as it slides into place.

When Electron reads `app.asar` into memory, `libgk_preload_shim.so` intercepts the `read`/`pread` buffer and replaces the panel transition CSS and theme variables in RAM before Electron parses them. The detail panel opens immediately in a single layout pass, and `app.asar` on disk stays unmodified.

### Excessive CI Tags and Remote-Tracking Branches

Repositories that generate thousands of automated CI tags and release branches (`candidate/*`, `release/*`, `platform/*`) accumulate large `.git/packed-refs` files and `500+ KB` `~/.gitkraken/profiles/*/repoSettings/*.json` files (`remoteHeadCollectionByRemoteName`), slowing down background fetches, `git rev-list --stdin`, and synchronous `JSON.parse` / `JSON.stringify` calls on every tab switch.

On install (and periodically in `watch-daemon` when the interval elapses or tag/remote ref counts spike), the optimizer backs up existing ref SHAs (`pre_install_refs.json`) and trims both `refs/tags/*` and `refs/remotes/origin/*` matching `keep_recent_by_pattern` down to the `N` most recent entries while keeping 100% of non-pattern refs, local branches, tracked upstreams, and checked-out worktree `HEAD`s. It also trims pruned `refs/tags/*` entries from `remoteHeadCollectionByRemoteName` and `tags` inside GitKraken's `repoSettings` files, adds negative tag fetch refspecs to `.git/config`, and filters `ls-remote --tags` and `fetch` through `gitkraken-git`.

### Stale Graph in Linked Worktrees

GitKraken only watches `.git/` changes inside the active working directory. In a linked worktree (`git worktree add`), the Git metadata directory lives outside the working tree under the main repository's `.git/worktrees/` folder, so running `git commit` or `git rebase` in a terminal does not update the graph.

`gitkraken-launcher` runs a lightweight background process (`watch-daemon`) for the duration of the GitKraken session. It watches the `HEAD` and branch files of each linked worktree and signals GitKraken's watcher to reload the graph whenever a ref changes.
