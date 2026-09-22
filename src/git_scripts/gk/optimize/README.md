# GitKraken Worktree Optimizer (`git-gk-optimize`)

Optimizes GitKraken Desktop (`v12.x` on Linux) when working with large repositories and linked Git worktrees (`git worktree add`).

## Overview

In large repositories and monorepos with multiple linked Git worktrees, GitKraken Desktop hits three common bottlenecks:

1. **Symlink & Build-Directory Watcher Crawl**:
   GitKraken's native file watcher **NSFW** (*Node Sentinel File Watcher*, `@axosoft/nsfw` / `nsfw.node`) calls `stat64()` inside `InotifyNode::isDirectory`, which follows symlinks (such as `bazel-*` output symlinks) into external build caches and recursively crawls large generated directories (`node_modules`, `.venv`, `.pixi`, `target`), causing multi-second UI stalls on every tab switch.
1. **High-Volume CI Tag Bloat**:
   Accumulated automated CI and release tags (`candidate/*`, `release/*`, `platform/*`) bloat `.git/packed-refs` and GitKraken's per-repo `repoSettings/*` JSON files, which GitKraken re-reads and writes to disk repeatedly during worktree switches.
1. **Missing Linked Worktree Auto-Refresh**:
   GitKraken's `watchWorkDirWithNsfw` (NSFW = *Node Sentinel File Watcher*) filter checks whether changed paths start with `".git/"` relative to the worktree root. Because a linked worktree's Git directory lives outside the working tree at `<common-git-dir>/worktrees/<name>` (`"../..."`), terminal `git` commands (`git rebase-prefix`, `git evolve`, `git commit`) do not trigger an automatic UI commit-graph refresh.

## Architecture

| File / Directory                                  | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `csrc/CMakeLists.txt` & `csrc/gk_nsfw_nofollow.c` | Compiled hermetically via **Pixi + CMake (`Ninja`)** (`pixi run build-gk-shim`) into `~/.config/gitkraken-optimizer/libgk_nsfw_nofollow.so`. Uses `dladdr` to intercept `stat64`/`__xstat64` calls strictly from `nsfw.node`: preserves `stat64` on repository/worktree roots (`<path>/.git` exists) while delegating child directory checks inside `InotifyNode` to `lstat64` and skipping configured build directories (`node_modules`, `.venv`, `.pixi`, `target`). All symlinks in the working tree remain intact. |
| `config.py` & `models.py`                         | Validates `~/.config/gitkraken-optimizer/config.yaml` (and `--config` / `--keep-recent-tags` CLI overrides) using `Pydantic` + `PyYAML`, saving the active configuration to `<common-git-dir>/gk-optimizer/config.yaml`.                                                                                                                                                                                                                                                                                               |
| `tags.py`                                         | Preserves 100% of unmatched normal tags (`v*`, etc.) and keeps the `N` most recent tags per configured pattern (`keep_recent_by_pattern`). Prunes older (`(N+1)th+`) tags via `git update-ref --stdin` after backing up their SHAs to `<common-git-dir>/gk-optimizer/pre_install_refs.json`.                                                                                                                                                                                                                           |
| `state.py`                                        | Records `pre_install` and `applied` values in `<common-git-dir>/gk-optimizer/state.yaml`, adds Git 2.29+ negative tag refspecs (`^refs/tags/...`) from `blocked_fetch_patterns` to `remote.origin.fetch`, trims pruned tag entries from `~/.gitkraken/profiles/*/repoSettings/*` (leaving `repoInitDetails` open tabs in `profile` untouched), and enforces Compare-And-Swap (`CAS`) restoration on `uninstall`.                                                                                                       |
| `shim.py`                                         | Installs `~/.config/gitkraken-optimizer/gitkraken-git` (`selectedGitPath` wrapper that scrubs `LD_PRELOAD` before invoking `/usr/bin/git` and applies `keep_recent_by_pattern` to `ls-remote --tags`), `~/.config/gitkraken-optimizer/gitkraken-launcher`, and the XDG desktop entry `~/.local/share/applications/gitkraken.desktop` (`GitKraken (Optimized)`).                                                                                                                                                        |
| `watcher.py`                                      | `flock`-guarded singleton `watch-daemon` (auto-exiting when GitKraken's PID closes) that watches `.git/worktrees/*/{HEAD,ORIG_HEAD}`, `.git/` (`packed-refs` atomic renames), and `.git/refs/tags/<prefix>/`. Emits `IN_MOVE_SELF` nudges for worktree UI refresh and idempotently trims `(N+1)th+` CI tags when `count > N`.                                                                                                                                                                                          |

## Configuration (`config.yaml`)

`git gk-optimize install` writes a configuration to `~/.config/gitkraken-optimizer/config.yaml` (and `<common-git-dir>/gk-optimizer/config.yaml`):

```yaml
tags:
  keep_other_tags: true
  prune_interval_hours: 12.0
  keep_recent_by_pattern:
    "candidate/*": 5
    "release/*": 5
    "platform/*": 5
  blocked_fetch_patterns:
    - "candidate/20*"
    - "platform/20*"
    - "release/20*"

watcher:
  ignored_dirs:
    - "node_modules"
    - ".venv"
    - ".pixi"
    - "target"
```

## Usage

```bash
# Build the CMake native library directly via Pixi
pixi run build-gk-shim

# Install optimizations for a repository and its linked worktrees
git gk-optimize install ~/path/to/repo --close-gitkraken

# Override how many recent tags to keep per pattern (5) or pass a custom YAML file
git gk-optimize install ~/path/to/repo --config custom.yaml --keep-recent-tags 5

# Verify installation status (exits 0 if all checks pass, 1 otherwise)
git gk-optimize verify ~/path/to/repo --expect installed

# Safely revert via Compare-And-Swap (preserving any post-install user changes)
git gk-optimize uninstall ~/path/to/repo --close-gitkraken
```
