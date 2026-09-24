# GitKraken Worktree Optimizer (`git-gk-optimize`)

## Overview

GitKraken Desktop on Linux degrades on large repositories and linked Git worktrees (`git worktree add`): its file watcher follows symlinks into build caches, thousands of automated CI tags slow down background fetches and tab switches, commit detail panels stutter on open, and terminal Git commands inside linked worktrees do not refresh the commit graph.

`git-gk-optimize` fixes these bottlenecks out-of-tree (`~/.config/gitkraken-optimizer/`) without modifying `/usr/share/gitkraken/` on disk, so optimizations survive system package updates and can be cleanly reverted at any time.

## Architecture

### Install and Uninstall (`git gk-optimize`)

- [`shim_builder.py`](shim_builder.py) and [`gitkraken_launcher.py`](gitkraken_launcher.py): Builds `libgk_preload_shim.so` with CMake and writes `gitkraken-launcher`, `gitkraken-git`, `watched_repos.json`, and `~/.local/share/applications/gitkraken.desktop`.
- [`config_loader.py`](config_loader.py) and [`models.py`](models.py): Loads [`config.yaml`](config.yaml) and symlinks it into `~/.config/gitkraken-optimizer/` and `<common-git-dir>/gk-optimizer/`.
- [`tag_pruner.py`](tag_pruner.py): Backs up pre-existing tag SHAs (`pre_install_refs.json`) and trims CI tag namespaces to the configured retention window.
- [`state_manager.py`](state_manager.py): Configures negative fetch refspecs in `.git/config`, updates GitKraken profile settings, and restores original state on `uninstall`.

### Runtime (`gitkraken-launcher`)

`gitkraken.desktop` launches `/usr/share/gitkraken/gitkraken` through `~/.config/gitkraken-optimizer/gitkraken-launcher`, which exports `LD_PRELOAD=libgk_preload_shim.so` and starts `watch-daemon`:

- [`csrc/gk_preload_shim.c`](csrc/gk_preload_shim.c) (`libgk_preload_shim.so`): `LD_PRELOAD` library that prunes `nsfw.node` directory traversal, patches `app.asar` UI transition rules in memory, and automatically strips itself from `LD_PRELOAD` in child shells and subprocesses.
- [`git_wrapper.py`](git_wrapper.py) (`gitkraken-git`): `selectedGitPath` wrapper that strips `LD_PRELOAD` for child Git commands and filters `ls-remote --tags` and `fetch`.
- [`worktree_watcher.py`](worktree_watcher.py) (`watch-daemon`): Session daemon bound to GitKraken's PID that refreshes linked worktrees on ref changes and re-trims CI tags after fetches.

## Usage

```bash
# Install optimizations for a repository and its linked worktrees
git gk-optimize install ~/path/to/repo --close-gitkraken

# Override the tag retention count or pass a custom YAML configuration
git gk-optimize install ~/path/to/repo --config custom.yaml --keep-recent-tags 5

# Verify installation state (exits 0 if all checks pass)
git gk-optimize verify ~/path/to/repo --expect installed

# Restore original repository refs and user settings
git gk-optimize uninstall ~/path/to/repo --close-gitkraken
```

## Issues and Solutions

### Symlink and Build Directory Crawling

GitKraken's file watcher (`nsfw.node`) recursively walks the working tree with `stat64`, which follows symlinks into external build caches (`bazel-*`) and large dependency folders (`node_modules`, `.venv`, `.pixi`, `target`), registering hundreds of thousands of `inotify` watches and stalling tab switches.

`libgk_preload_shim.so` intercepts `stat` calls originating from `nsfw.node` (`dladdr` check) so watcher behavior matches how Git tracks files:

- **Symlinked repository and submodule roots are still followed**: If a symlink itself contains `.git` (for example, opening a repository via a symlinked directory path), the shim resolves it as a directory so GitKraken watches the repository normally.
- **Git-tracked symlinks are still watched for changes without crawling targets**: Git stores working-tree symlinks as mode `120000` pointer entries (`lstat`) rather than indexing files inside the target directory. Returning `S_ISLNK` stops `nsfw.node` from recursing into external symlink targets (such as `bazel-*` output caches), while the parent directory's `inotify` watch still detects whenever a symlink itself is created, deleted, or retargeted.
- **Configured directories are still skipped**: Real directories matching `watcher.ignored_dirs` in [`config.yaml`](config.yaml) are masked from `nsfw.node` directory recursion, while normal filesystem calls from `libgit2`, `git`, and the rest of GitKraken remain untouched.

### Commit Detail Panel Animation Lag

Selecting a commit opens the right-hand detail panel with a `250ms` flexbox width transition. Because the commit graph resizes on every animation frame, the detail panel noticeably stutters as it slides into place.

When Electron reads `app.asar` into memory, `libgk_preload_shim.so` intercepts the `read`/`pread` buffer and replaces the panel transition CSS and theme variables in RAM before Electron parses them. The detail panel opens immediately in a single layout pass, and `app.asar` on disk stays unmodified.

### Excessive CI Tags

Repositories that generate thousands of automated CI tags (`candidate/*`, `release/*`, `platform/*`) accumulate large `.git/packed-refs` and GitKraken settings files, slowing down background fetches and tab switches.

On install, the optimizer backs up all existing tag references and trims configured CI tag patterns down to the `N` most recent tags (keeping all other tags intact). To stop background fetches from re-downloading old tags, it adds negative fetch refspecs to `.git/config` and routes GitKraken's CLI Git calls through `gitkraken-git` to filter remote tag listings.

### Stale Graph in Linked Worktrees

GitKraken only watches `.git/` changes inside the active working directory. In a linked worktree (`git worktree add`), the Git metadata directory lives outside the working tree under the main repository's `.git/worktrees/` folder, so running `git commit` or `git rebase` in a terminal does not update the graph.

`gitkraken-launcher` runs a lightweight background process (`watch-daemon`) for the duration of the GitKraken session. It watches the `HEAD` and branch files of each linked worktree and signals GitKraken's watcher to reload the graph whenever a ref changes.
