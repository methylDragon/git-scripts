"""Compare-And-Swap (CAS) saved state (state.yaml) and GK settings manager."""

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


def get_state_path(common_git_dir: Path) -> Path:
    """Returns <common-git-dir>/gk-optimizer/state.yaml."""
    return common_git_dir / "gk-optimizer" / "state.yaml"


def read_state(common_git_dir: Path) -> dict[str, Any]:
    """Reads state.yaml or returns an empty state dictionary."""
    path = get_state_path(common_git_dir)
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    return {
        "fetch_refspecs": {},
        "git_config": {},
        "gk_profiles": {},
        "gk_repo_settings": {},
    }


def write_state(common_git_dir: Path, state: dict[str, Any]) -> None:
    """Writes state.yaml atomically."""
    path = get_state_path(common_git_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".yaml.tmp")
    payload = yaml.safe_dump(state, sort_keys=True)
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


REPO_PERF_CONFIG: dict[str, str] = {
    "core.commitGraph": "true",
    "core.untrackedCache": "true",
    "fetch.writeCommitGraph": "true",
    "fetch.prune": "true",
}


def _get_single_git_config_value(common_git_dir: Path, key: str) -> str | None:
    """Returns the local git config value for key, or None if unset."""
    proc = subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "config",
            "--local",
            "--get",
            key,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def apply_repo_perf_config(
    common_git_dir: Path,
    state: dict[str, Any],
) -> None:
    """Sets NodeGit-safe git performance settings and saves CAS state."""
    cfg_state = state.setdefault("git_config", {})
    for key, target_val in REPO_PERF_CONFIG.items():
        cur_val = _get_single_git_config_value(common_git_dir, key)
        if key not in cfg_state:
            cfg_state[key] = {
                "pre_install": cur_val,
                "applied": target_val,
            }
        if cur_val != target_val:
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(common_git_dir),
                    "config",
                    "--local",
                    key,
                    target_val,
                ],
                check=False,
                capture_output=True,
                text=True,
            )


def revert_repo_perf_config(
    common_git_dir: Path,
    state: dict[str, Any],
) -> None:
    """Reverts git performance settings using strict Compare-And-Swap."""
    cfg_state = state.get("git_config", {})
    if not isinstance(cfg_state, dict):
        return
    for key, entry in cfg_state.items():
        if not isinstance(entry, dict):
            continue
        cur_val = _get_single_git_config_value(common_git_dir, key)
        if cur_val != entry.get("applied"):
            continue
        pre_val = entry.get("pre_install")
        cmd = ["git", "--git-dir", str(common_git_dir), "config", "--local"]
        if pre_val is None:
            cmd.extend(["--unset-all", key])
        else:
            cmd.extend([key, str(pre_val)])
        subprocess.run(cmd, check=False, capture_output=True, text=True)


def _get_git_config_values(common_git_dir: Path, key: str) -> list[str]:
    """Returns all values for a git config key in common_git_dir."""
    proc = subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "config",
            "--local",
            "--get-all",
            key,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _normalize_negative_tag_refspec(pattern: str) -> str:
    """Normalizes 'candidate/2023*' into '^refs/tags/candidate/2023*'."""
    clean = pattern.lstrip("^")
    if not clean.startswith("refs/"):
        clean = f"refs/tags/{clean}"
    return f"^{clean}"


def _unset_fetch_refspec(common_git_dir: Path, spec: str) -> None:
    """Removes a specific refspec value from local remote.origin.fetch."""
    subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "config",
            "--local",
            "--unset-all",
            "--fixed-value",
            "remote.origin.fetch",
            spec,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def apply_fetch_refspecs(
    common_git_dir: Path,
    exclude_globs: list[str],
    state: dict[str, Any],
) -> None:
    """Adds negative refspecs (^refs/tags/...) and prunes stale added ones."""
    existing = _get_git_config_values(common_git_dir, "remote.origin.fetch")
    neg_specs = [_normalize_negative_tag_refspec(g) for g in exclude_globs]
    fetch_state = state.setdefault("fetch_refspecs", {})
    entry = fetch_state.get("remote.origin.fetch")
    if not isinstance(entry, dict):
        pre_install = [s for s in existing if not s.startswith("^refs/tags/")]
        prev_added: list[str] = []
        entry = {"pre_install": pre_install, "added": neg_specs}
        fetch_state["remote.origin.fetch"] = entry
    else:
        pre_install = list(entry.get("pre_install", []))
        prev_added = list(entry.get("added", []))
        entry["added"] = neg_specs

    stale_specs = [
        spec
        for spec in existing
        if spec not in pre_install
        and spec not in neg_specs
        and (spec in prev_added or spec.startswith("^refs/tags/"))
    ]
    for spec in stale_specs:
        _unset_fetch_refspec(common_git_dir, spec)

    for spec in neg_specs:
        if spec not in existing:
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(common_git_dir),
                    "config",
                    "--local",
                    "--add",
                    "remote.origin.fetch",
                    spec,
                ],
                check=True,
                capture_output=True,
                text=True,
            )


def revert_fetch_refspecs(
    common_git_dir: Path,
    state: dict[str, Any],
) -> None:
    """Removes only negative refspecs added by install, keeping user rules."""
    entry = state.get("fetch_refspecs", {}).get("remote.origin.fetch")
    if not isinstance(entry, dict):
        return
    added_specs: list[str] = entry.get("added", [])
    current_specs = _get_git_config_values(
        common_git_dir, "remote.origin.fetch"
    )
    for spec in added_specs:
        if spec in current_specs:
            _unset_fetch_refspec(common_git_dir, spec)


def _trim_tags_section(
    rs_data: dict[str, Any],
    kept_tags: set[str],
) -> dict[str, Any]:
    """Trims top-level tags dict in rs_data and returns removed entries."""
    tags_section = rs_data.get("tags")
    if not isinstance(tags_section, dict) or not tags_section:
        return {}
    removed = {k: v for k, v in tags_section.items() if k not in kept_tags}
    if removed:
        rs_data["tags"] = {
            k: v for k, v in tags_section.items() if k in kept_tags
        }
    return removed


def _partition_remote_heads(
    heads_map: dict[str, Any],
    kept_tags: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Splits a remote's head map into (kept_entries, removed_tag_entries)."""
    kept_heads: dict[str, Any] = {}
    removed_heads: dict[str, Any] = {}
    for ref_key, ref_val in heads_map.items():
        if (
            ref_key.startswith("refs/tags/")
            and ref_key.removeprefix("refs/tags/") not in kept_tags
        ):
            removed_heads[ref_key] = ref_val
        else:
            kept_heads[ref_key] = ref_val
    return kept_heads, removed_heads


def _trim_remote_heads_section(
    rs_data: dict[str, Any],
    kept_tags: set[str],
) -> dict[str, dict[str, Any]]:
    """Trims pruned refs/tags/* from remoteHeadCollectionByRemoteName."""
    remote_col = rs_data.get("remoteHeadCollectionByRemoteName")
    if not isinstance(remote_col, dict) or not remote_col:
        return {}
    removed_by_remote: dict[str, dict[str, Any]] = {}
    for remote_name, heads_map in remote_col.items():
        if not isinstance(heads_map, dict) or not heads_map:
            continue
        kept_heads, removed_heads = _partition_remote_heads(
            heads_map, kept_tags
        )
        if removed_heads:
            remote_col[remote_name] = kept_heads
            removed_by_remote[remote_name] = removed_heads
    return removed_by_remote


def _merge_missing_entries(
    target_dict: dict[str, Any],
    source_dict: dict[str, Any],
) -> None:
    """Inserts missing keys from source_dict into target_dict."""
    for key, val in source_dict.items():
        target_dict.setdefault(key, val)


def _record_removed_repo_settings(
    state: dict[str, Any],
    rs_key: str,
    removed_tags: dict[str, Any],
    removed_remotes: dict[str, dict[str, Any]],
) -> None:
    """Merges removed tag and remoteHead entries into state.yaml."""
    rs_state = state.setdefault("gk_repo_settings", {})
    entry = rs_state.get(rs_key)
    if not isinstance(entry, dict):
        entry = {}
        rs_state[rs_key] = entry
    if removed_tags:
        saved_tags = entry.setdefault("removed_tags", {})
        _merge_missing_entries(saved_tags, removed_tags)
    if removed_remotes:
        saved_remotes = entry.setdefault("removed_remote_heads", {})
        for rem_name, rem_heads in removed_remotes.items():
            rem_bucket = saved_remotes.setdefault(rem_name, {})
            _merge_missing_entries(rem_bucket, rem_heads)


def _trim_repo_settings_file(
    rs_file: Path,
    kept_tags: set[str],
    state: dict[str, Any],
) -> bool:
    """Trims pruned tags from a single repoSettings JSON file."""
    if not rs_file.is_file():
        return False
    try:
        rs_data = json.loads(rs_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(rs_data, dict):
        return False
    removed_tags = _trim_tags_section(rs_data, kept_tags)
    removed_remotes = _trim_remote_heads_section(rs_data, kept_tags)
    if not removed_tags and not removed_remotes:
        return False
    _record_removed_repo_settings(
        state, str(rs_file), removed_tags, removed_remotes
    )
    rs_file.write_text(json.dumps(rs_data), encoding="utf-8")
    return True


def _apply_profile_git_path(
    profile_file: Path,
    gitkraken_git_path: Path,
    state: dict[str, Any],
) -> None:
    """Sets selectedGitPath in profile_file and records pre_install state."""
    if not profile_file.is_file():
        return
    data = json.loads(profile_file.read_text(encoding="utf-8"))
    pre_val = data.get("selectedGitPath")
    applied_val = str(gitkraken_git_path)
    key = str(profile_file)
    if key not in state.get("gk_profiles", {}):
        state.setdefault("gk_profiles", {})[key] = {
            "pre_install": pre_val,
            "applied": applied_val,
        }
    # Never touch repoInitDetails (open tabs)
    data["selectedGitPath"] = applied_val
    profile_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def apply_gk_settings(
    gk_root: Path,
    gitkraken_git_path: Path,
    kept_tags: set[str],
    state: dict[str, Any],
    trim_tags: bool = True,
) -> int:
    """Sets selectedGitPath in profile and trims pruned tag bloat."""
    profiles_dir = gk_root / "profiles"
    if not profiles_dir.is_dir():
        return 0

    cleaned_files = 0
    for profile_dir in sorted(profiles_dir.iterdir()):
        if not profile_dir.is_dir():
            continue
        _apply_profile_git_path(
            profile_dir / "profile", gitkraken_git_path, state
        )
        repo_settings_dir = profile_dir / "repoSettings"
        if not trim_tags or not repo_settings_dir.is_dir():
            continue
        cleaned_files += sum(
            1
            for rs_file in sorted(repo_settings_dir.iterdir())
            if _trim_repo_settings_file(rs_file, kept_tags, state)
        )

    return cleaned_files


def _restore_tags_dict(
    target_dict: dict[str, Any],
    removed_entries: dict[str, Any],
) -> bool:
    """Restores missing keys from removed_entries into target_dict."""
    modified = False
    for key, val in removed_entries.items():
        if key not in target_dict:
            target_dict[key] = val
            modified = True
    return modified


def _restore_top_level_tags_dict(
    rs_data: dict[str, Any],
    removed_tags: Any,
) -> bool:
    """Restores missing top-level tags entries into rs_data."""
    if not isinstance(removed_tags, dict) or not removed_tags:
        return False
    tags_sec = rs_data.setdefault("tags", {})
    if not isinstance(tags_sec, dict):
        return False
    return _restore_tags_dict(tags_sec, removed_tags)


def _restore_remote_heads_dict(
    rs_data: dict[str, Any],
    removed_remotes: Any,
) -> bool:
    """Restores missing remoteHeadCollectionByRemoteName tag entries."""
    if not isinstance(removed_remotes, dict) or not removed_remotes:
        return False
    remote_col = rs_data.setdefault("remoteHeadCollectionByRemoteName", {})
    if not isinstance(remote_col, dict):
        return False
    modified = False
    for rem_name, rem_heads in removed_remotes.items():
        if not isinstance(rem_heads, dict) or not rem_heads:
            continue
        rem_bucket = remote_col.setdefault(rem_name, {})
        if isinstance(rem_bucket, dict) and _restore_tags_dict(
            rem_bucket, rem_heads
        ):
            modified = True
    return modified


def _restore_repo_settings_entry(
    rs_file: Path,
    entry: dict[str, Any],
) -> None:
    """Restores removed tags into a repoSettings JSON file safely."""
    try:
        rs_data = json.loads(rs_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(rs_data, dict):
        return
    tags_mod = _restore_top_level_tags_dict(rs_data, entry.get("removed_tags"))
    rem_mod = _restore_remote_heads_dict(
        rs_data, entry.get("removed_remote_heads")
    )
    if tags_mod or rem_mod:
        rs_file.write_text(json.dumps(rs_data), encoding="utf-8")


def _revert_profile_selected_git_path(
    profile_file: Path,
    entry: dict[str, Any],
) -> None:
    """Reverts selectedGitPath in profile_file using strict CAS."""
    data = json.loads(profile_file.read_text(encoding="utf-8"))
    if data.get("selectedGitPath") != entry.get("applied"):
        return
    pre_val = entry.get("pre_install")
    if pre_val is None:
        data.pop("selectedGitPath", None)
    else:
        data["selectedGitPath"] = pre_val
    profile_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def revert_gk_settings(
    state: dict[str, Any],
    revert_profiles: bool = True,
) -> None:
    """Reverts selectedGitPath and repoSettings tags using strict CAS."""
    profiles_map = state.get("gk_profiles", {}) if revert_profiles else {}
    for profile_str, entry in profiles_map.items():
        profile_file = Path(profile_str)
        if profile_file.is_file() and isinstance(entry, dict):
            _revert_profile_selected_git_path(profile_file, entry)

    for rs_str, entry in state.get("gk_repo_settings", {}).items():
        rs_file = Path(rs_str)
        if not rs_file.is_file() or not isinstance(entry, dict):
            continue
        _restore_repo_settings_entry(rs_file, entry)
