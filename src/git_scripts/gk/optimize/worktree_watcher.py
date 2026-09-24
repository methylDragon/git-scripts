"""Worktree watcher for IN_MOVE_SELF refresh and rolling tag window pruning."""

import json
import os
import time
from pathlib import Path

from filelock import FileLock, Timeout  # pylint: disable=import-error

from git_scripts.gk.optimize.config_loader import (
    get_repo_config_path,
    read_config,
)
from git_scripts.gk.optimize.tag_pruner import (
    analyze_prunable_tags,
    prune_tags,
)


def _is_pid_alive(pid: int | None) -> bool:
    """Checks if a monitored process PID is still running."""
    if pid is None or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _has_active_git_locks(wt_gitdir: Path) -> bool:
    """Returns True if Git or a rebase/merge holds lockfiles in wt_gitdir."""
    lock_names = (
        "index.lock",
        "HEAD.lock",
        "rebase-merge",
        "rebase-apply",
        "MERGE_HEAD",
    )
    return any((wt_gitdir / name).exists() for name in lock_names)


def nudge_worktree_nsfw(wt_gitdir: Path) -> bool:
    """Emits IN_MOVE_SELF for NSFW (Node Sentinel File Watcher) refresh."""
    if not wt_gitdir.is_dir() or _has_active_git_locks(wt_gitdir):
        return False
    tmp_dir = wt_gitdir.with_name(f".{wt_gitdir.name}.gk-nudge")
    try:
        os.rename(wt_gitdir, tmp_dir)
        os.rename(tmp_dir, wt_gitdir)
        return True
    except OSError:
        if tmp_dir.exists() and not wt_gitdir.exists():
            try:
                os.rename(tmp_dir, wt_gitdir)
            except OSError:
                pass
        return False


def _recover_nudge_dirs(worktrees_dir: Path) -> None:
    """Restores any interrupted `.{name}.gk-nudge` directories in worktrees."""
    if not worktrees_dir.is_dir():
        return
    for wt_dir in sorted(worktrees_dir.iterdir()):
        if not (
            wt_dir.is_dir()
            and wt_dir.name.startswith(".")
            and wt_dir.name.endswith(".gk-nudge")
        ):
            continue
        orig_dir = wt_dir.parent / wt_dir.name[1 : -len(".gk-nudge")]
        if orig_dir.exists():
            continue
        try:
            os.rename(wt_dir, orig_dir)
        except OSError:
            pass


def _lookup_packed_ref_sha(common_git_dir: Path, ref_rel: str) -> str:
    """Finds the target SHA for ref_rel inside packed-refs if present."""
    packed = common_git_dir / "packed-refs"
    try:
        if not packed.is_file():
            return ""
        suffix = f" {ref_rel}"
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(suffix) and not line.startswith(("#", "^")):
                return line.split()[0]
    except OSError:
        pass
    return ""


def _resolve_worktree_head_signature(
    common_git_dir: Path, wt_dir: Path
) -> str:
    """Returns 'head_raw|resolved_sha|orig_head' for a linked worktree HEAD."""
    head_file = wt_dir / "HEAD"
    try:
        head_raw = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    resolved_sha = head_raw
    if head_raw.startswith("ref: "):
        ref_rel = head_raw[5:].strip()
        loose_ref = common_git_dir / ref_rel
        try:
            resolved_sha = (
                loose_ref.read_text(encoding="utf-8").strip()
                if loose_ref.is_file()
                else (
                    _lookup_packed_ref_sha(common_git_dir, ref_rel)
                    or resolved_sha
                )
            )
        except OSError:
            pass
    orig_head = ""
    orig_file = wt_dir / "ORIG_HEAD"
    try:
        if orig_file.is_file():
            orig_head = orig_file.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return f"{head_raw}|{resolved_sha}|{orig_head}"


def _snapshot_worktree_heads(common_git_dir: Path) -> dict[str, str]:
    """Captures HEAD ref and resolved commit SHA across linked worktrees."""
    worktrees_dir = common_git_dir / "worktrees"
    if not worktrees_dir.is_dir():
        return {}
    state: dict[str, str] = {}
    for wt_dir in sorted(worktrees_dir.iterdir()):
        if not wt_dir.is_dir() or wt_dir.name.startswith("."):
            continue
        sig = _resolve_worktree_head_signature(common_git_dir, wt_dir)
        if sig:
            state[wt_dir.name] = sig
    return state


def _snapshot_tag_state(common_git_dir: Path) -> float:
    """Returns a combined mtime marker for packed-refs and loose tag dirs."""
    mtimes: list[float] = []
    packed = common_git_dir / "packed-refs"
    try:
        mtimes.append(packed.stat().st_mtime)
    except OSError:
        pass
    tags_dir = common_git_dir / "refs" / "tags"
    if tags_dir.is_dir():
        try:
            mtimes.append(tags_dir.stat().st_mtime)
            for child in tags_dir.iterdir():
                if child.is_dir():
                    mtimes.append(child.stat().st_mtime)
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


PACKED_REFS_FLOOD_BYTES = 8192


def _get_packed_refs_size(common_git_dir: Path) -> int:
    """Returns the size in bytes of packed-refs, or 0 if absent."""
    packed = common_git_dir / "packed-refs"
    try:
        return packed.stat().st_size if packed.is_file() else 0
    except OSError:
        return 0


def record_prune_marker(
    common_git_dir: Path,
    now_epoch: float | None = None,
) -> Path:
    """Writes current epoch and packed-refs size to last_tag_prune.json."""
    marker = common_git_dir / "gk-optimizer" / "last_tag_prune.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    epoch = now_epoch if now_epoch is not None else time.time()
    payload = {
        "last_prune_epoch": epoch,
        "packed_refs_size": _get_packed_refs_size(common_git_dir),
    }
    marker.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return marker


def should_prune_tags(
    common_git_dir: Path,
    now_epoch: float | None = None,
) -> bool:
    """Returns True if >= prune_interval_hours passed or packed-refs spiked."""
    marker = common_git_dir / "gk-optimizer" / "last_tag_prune.json"
    if not marker.is_file():
        return True
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        last_epoch = float(data.get("last_prune_epoch", 0.0))
        last_size = int(data.get("packed_refs_size", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return True

    if (
        _get_packed_refs_size(common_git_dir) - last_size
        > PACKED_REFS_FLOOD_BYTES
    ):
        return True

    cfg_path = get_repo_config_path(common_git_dir)
    config = read_config(cfg_path if cfg_path.is_file() else None)
    interval_sec = max(0.0, float(config.tags.prune_interval_hours)) * 3600.0
    now = now_epoch if now_epoch is not None else time.time()
    return (now - last_epoch) >= interval_sec


def prune_excess_tags(common_git_dir: Path) -> int:
    """Prunes (N+1)th+ tags if any prefix exceeds its rolling window."""
    cfg_path = get_repo_config_path(common_git_dir)
    config = read_config(cfg_path if cfg_path.is_file() else None)
    to_prune, _ = analyze_prunable_tags(common_git_dir, config)
    if not to_prune:
        record_prune_marker(common_git_dir)
        return 0
    backup_file = common_git_dir / "gk-optimizer" / "pre_install_refs.json"
    pruned = prune_tags(common_git_dir, to_prune, backup_file=backup_file)
    record_prune_marker(common_git_dir)
    return pruned


def _load_watched_git_dirs(primary_git_dir: Path) -> list[Path]:
    """Returns deduplicated list of registered common_git_dirs to watch."""
    dirs: list[Path] = [primary_git_dir.resolve()]
    repos_file = (
        Path.home() / ".config" / "gitkraken-optimizer" / "watched_repos.json"
    )
    if not repos_file.is_file():
        return dirs
    try:
        data = json.loads(repos_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dirs
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
        return dirs
    for raw in data["repos"]:
        candidate = Path(str(raw)).resolve()
        if candidate.is_dir() and candidate not in dirs:
            dirs.append(candidate)
    return dirs


def _poll_single_repo(
    git_dir: Path,
    prev_wt_by_repo: dict[Path, dict[str, str]],
    prev_tag_by_repo: dict[Path, float],
) -> None:
    """Checks worktree HEAD changes and lazy tag prune conditions."""
    prev_wt = prev_wt_by_repo.get(git_dir, {})
    _recover_nudge_dirs(git_dir / "worktrees")
    cur_wt = _snapshot_worktree_heads(git_dir)
    for wt_name, head_sig in cur_wt.items():
        if wt_name in prev_wt and head_sig != prev_wt[wt_name]:
            time.sleep(0.25)
            nudge_worktree_nsfw(git_dir / "worktrees" / wt_name)
    prev_wt_by_repo[git_dir] = cur_wt

    cur_tag_mtime = _snapshot_tag_state(git_dir)
    if cur_tag_mtime > prev_tag_by_repo.get(
        git_dir, 0.0
    ) and should_prune_tags(git_dir):
        prune_excess_tags(git_dir)
        prev_tag_by_repo[git_dir] = _snapshot_tag_state(git_dir)


def execute_watch_daemon(
    common_git_dir: Path,
    gk_pid: int | None = None,
    poll_interval_sec: float = 0.5,
    max_iterations: int | None = None,
) -> bool:
    """Runs the singleton flock-guarded worktree and tag watcher loop."""
    opt_dir = common_git_dir / "gk-optimizer"
    opt_dir.mkdir(parents=True, exist_ok=True)
    lock_file = opt_dir / "watch-daemon.lock"
    lock = FileLock(str(lock_file), timeout=0.05)

    try:
        with lock:
            git_dirs = _load_watched_git_dirs(common_git_dir)
            for d in git_dirs:
                _recover_nudge_dirs(d / "worktrees")
                if should_prune_tags(d):
                    prune_excess_tags(d)
            prev_wt = {d: _snapshot_worktree_heads(d) for d in git_dirs}
            prev_tag = {d: _snapshot_tag_state(d) for d in git_dirs}
            iterations = 0

            while _is_pid_alive(gk_pid):
                time.sleep(poll_interval_sec)
                for git_dir in _load_watched_git_dirs(common_git_dir):
                    if git_dir not in prev_wt:
                        _recover_nudge_dirs(git_dir / "worktrees")
                        prev_wt[git_dir] = _snapshot_worktree_heads(git_dir)
                        prev_tag[git_dir] = _snapshot_tag_state(git_dir)
                    _poll_single_repo(git_dir, prev_wt, prev_tag)

                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
            return True
    except Timeout:
        return True
