"""Rolling tag window analysis, update-ref pruning, and CAS restoration."""

import fnmatch
import json
import subprocess
from pathlib import Path

from git_scripts.gk.optimize.models import GkOptimizerConfig


def _list_repo_tags_sorted(common_git_dir: Path) -> list[tuple[str, str]]:
    """Returns all (tag_name, sha) pairs ordered newest-first."""
    proc = subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "for-each-ref",
            "--sort=-creatordate",
            "--sort=-v:refname",
            "--format=%(refname:short)\t%(objectname)",
            "refs/tags",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    tags: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        name, sha = line.split("\t", 1)
        if name.strip() and sha.strip():
            tags.append((name.strip(), sha.strip()))
    return tags


def analyze_tags_to_prune(
    common_git_dir: Path,
    config: GkOptimizerConfig,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Returns ((tag_name, sha) to prune, kept tag names)."""
    all_tags = _list_repo_tags_sorted(common_git_dir)
    windows = config.tags.keep_recent_by_pattern
    counts: dict[str, int] = dict.fromkeys(windows, 0)
    to_prune: list[tuple[str, str]] = []
    kept: list[str] = []

    for tag_name, sha in all_tags:
        matched_prefix: str | None = None
        for prefix in windows:
            if fnmatch.fnmatchcase(tag_name, prefix):
                matched_prefix = prefix
                break

        if matched_prefix is None:
            if config.tags.keep_other_tags:
                kept.append(tag_name)
            else:
                to_prune.append((tag_name, sha))
            continue

        limit = max(0, int(windows[matched_prefix]))
        if counts[matched_prefix] < limit:
            counts[matched_prefix] += 1
            kept.append(tag_name)
        else:
            to_prune.append((tag_name, sha))

    return to_prune, kept


def record_pruned_refs_backup(
    backup_file: Path,
    pruned_tags: list[tuple[str, str]],
) -> None:
    """Appends pruned (tag_name, sha) entries to pre_install_refs.json."""
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if backup_file.is_file():
        loaded = json.loads(backup_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = {str(k): str(v) for k, v in loaded.items()}

    for tag_name, sha in pruned_tags:
        full_ref = f"refs/tags/{tag_name}"
        if full_ref not in existing:
            existing[full_ref] = sha

    backup_file.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_tag_pruning(
    common_git_dir: Path,
    tags_to_prune: list[tuple[str, str]],
    backup_file: Path | None = None,
) -> int:
    """Atomically deletes (N+1)th+ tags via git update-ref and packs refs."""
    if not tags_to_prune:
        return 0

    if backup_file is not None:
        record_pruned_refs_backup(backup_file, tags_to_prune)

    stdin_lines = [
        f"delete refs/tags/{tag_name} {sha}" for tag_name, sha in tags_to_prune
    ]
    subprocess.run(
        ["git", "--git-dir", str(common_git_dir), "update-ref", "--stdin"],
        input="\n".join(stdin_lines) + "\n",
        text=True,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "pack-refs",
            "--all",
            "--prune",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return len(tags_to_prune)


def restore_pruned_tags_cas(
    common_git_dir: Path,
    backup_file: Path,
) -> int:
    """Restores pruned tags via zero-OID create CAS if ref is still absent."""
    if not backup_file.is_file():
        return 0

    current_proc = subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "for-each-ref",
            "--format=%(refname)",
            "refs/tags",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw_lines = current_proc.stdout.splitlines()
    existing_refs = {ln.strip() for ln in raw_lines if ln.strip()}

    loaded = json.loads(backup_file.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return 0

    create_lines = [
        f"create {full_ref} {sha}"
        for full_ref, sha in loaded.items()
        if full_ref and sha and full_ref not in existing_refs
    ]
    if not create_lines:
        return 0

    subprocess.run(
        ["git", "--git-dir", str(common_git_dir), "update-ref", "--stdin"],
        input="\n".join(create_lines) + "\n",
        text=True,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "pack-refs",
            "--all",
            "--prune",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return len(create_lines)
