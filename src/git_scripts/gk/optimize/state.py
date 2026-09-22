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
        "git_config": {},
        "fetch_refspecs": {},
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


def apply_negative_fetch_refspecs(
    common_git_dir: Path,
    exclude_globs: list[str],
    state: dict[str, Any],
) -> None:
    """Adds negative refspecs (^refs/tags/...) to remote.origin.fetch."""
    existing = _get_git_config_values(common_git_dir, "remote.origin.fetch")
    neg_specs = [_normalize_negative_tag_refspec(g) for g in exclude_globs]
    if "remote.origin.fetch" not in state.get("fetch_refspecs", {}):
        state.setdefault("fetch_refspecs", {})["remote.origin.fetch"] = {
            "pre_install": existing,
            "added": neg_specs,
        }

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


def revert_negative_fetch_refspecs_cas(
    common_git_dir: Path,
    state: dict[str, Any],
) -> None:
    """Removes only negative refspecs added by install, keeping user rules."""
    entry = state.get("fetch_refspecs", {}).get("remote.origin.fetch")
    if not isinstance(entry, dict):
        return
    added_specs: list[str] = entry.get("added", [])
    fetch_key = "remote.origin.fetch"
    current_specs = _get_git_config_values(common_git_dir, fetch_key)
    for spec in added_specs:
        if spec in current_specs:
            escaped_spec = spec.replace("^", r"\^")
            pattern = f"^{escaped_spec}$"
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(common_git_dir),
                    "config",
                    "--local",
                    "--unset-all",
                    "remote.origin.fetch",
                    pattern,
                ],
                check=False,
                capture_output=True,
                text=True,
            )


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
    tags_section = rs_data.get("tags")
    if not isinstance(tags_section, dict) or not tags_section:
        return False
    tags_items = tags_section.items()
    removed_tags = {k: v for k, v in tags_items if k not in kept_tags}
    if not removed_tags:
        return False
    rs_key = str(rs_file)
    if rs_key not in state.get("gk_repo_settings", {}):
        state.setdefault("gk_repo_settings", {})[rs_key] = {
            "removed_tags": removed_tags,
        }
    rs_data["tags"] = {k: v for k, v in tags_section.items() if k in kept_tags}
    rs_file.write_text(json.dumps(rs_data), encoding="utf-8")
    return True


def apply_gitkraken_profile_and_repo_settings(
    gk_root: Path,
    gitkraken_git_path: Path,
    kept_tags: set[str],
    state: dict[str, Any],
) -> int:
    """Sets selectedGitPath in profile and trims pruned tag bloat."""
    profiles_dir = gk_root / "profiles"
    if not profiles_dir.is_dir():
        return 0

    cleaned_files = 0
    for profile_dir in sorted(profiles_dir.iterdir()):
        if not profile_dir.is_dir():
            continue
        profile_file = profile_dir / "profile"
        if profile_file.is_file():
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
            profile_file.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )

        repo_settings_dir = profile_dir / "repoSettings"
        if not repo_settings_dir.is_dir():
            continue
        for rs_file in sorted(repo_settings_dir.iterdir()):
            if _trim_repo_settings_file(rs_file, kept_tags, state):
                cleaned_files += 1

    return cleaned_files


def _restore_repo_settings_entry(
    rs_file: Path,
    removed_tags: dict[str, Any],
) -> None:
    """Restores removed tags into a repoSettings JSON file safely."""
    try:
        rs_data = json.loads(rs_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    tags_sec = rs_data.setdefault("tags", {})
    if isinstance(tags_sec, dict):
        for tag_k, tag_v in removed_tags.items():
            if tag_k not in tags_sec:
                tags_sec[tag_k] = tag_v
        rs_file.write_text(json.dumps(rs_data), encoding="utf-8")


def revert_gitkraken_profile_and_repo_settings_cas(
    state: dict[str, Any],
) -> None:
    """Reverts selectedGitPath and repoSettings tags using strict CAS."""
    for profile_str, entry in state.get("gk_profiles", {}).items():
        profile_file = Path(profile_str)
        if not profile_file.is_file() or not isinstance(entry, dict):
            continue
        data = json.loads(profile_file.read_text(encoding="utf-8"))
        # Strict CAS: revert only if current value still equals applied value
        if data.get("selectedGitPath") == entry.get("applied"):
            pre_val = entry.get("pre_install")
            if pre_val is None:
                data.pop("selectedGitPath", None)
            else:
                data["selectedGitPath"] = pre_val
            profile_file.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )

    for rs_str, entry in state.get("gk_repo_settings", {}).items():
        rs_file = Path(rs_str)
        if not rs_file.is_file() or not isinstance(entry, dict):
            continue
        removed_tags = entry.get("removed_tags", {})
        if isinstance(removed_tags, dict) and removed_tags:
            _restore_repo_settings_entry(rs_file, removed_tags)
