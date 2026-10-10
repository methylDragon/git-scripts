"""Rolling tag and remote-ref window analysis, pruning, and CAS restoration."""

import fnmatch
import json
import subprocess
from pathlib import Path

from git_scripts.gk.optimize.models import GkOptimizerConfig


def _parse_tab_pairs(stdout: str) -> list[tuple[str, str]]:
    """Parses tab-separated name and SHA lines from git for-each-ref."""
    pairs: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        name, sha = line.split("\t", 1)
        if name.strip() and sha.strip():
            pairs.append((name.strip(), sha.strip()))
    return pairs


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
    return _parse_tab_pairs(proc.stdout)


def _list_remote_origin_branches_sorted(
    common_git_dir: Path,
) -> list[tuple[str, str]]:
    """Returns (branch_name, sha) under refs/remotes/origin newest-first."""
    cmd = [
        "git",
        "--git-dir",
        str(common_git_dir),
        "for-each-ref",
        "--sort=-committerdate",
        "--sort=-creatordate",
        "--sort=-v:refname",
        "--format=%(refname:lstrip=3)\t%(objectname)",
        "refs/remotes/origin",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return _parse_tab_pairs(proc.stdout) if proc.returncode == 0 else []


def _match_window_prefix(name: str, windows: dict[str, int]) -> str | None:
    """Returns the first matching pattern key in windows, or None."""
    for prefix in windows:
        if fnmatch.fnmatchcase(name, prefix):
            return prefix
    return None


def analyze_prunable_tags(
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
        matched_prefix = _match_window_prefix(tag_name, windows)
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


def _collect_local_heads_and_upstreams(
    common_git_dir: Path,
) -> tuple[set[str], set[str]]:
    """Returns protected (branch_names, tip_shas) from local heads/config."""
    names: set[str] = {"HEAD"}
    shas: set[str] = set()
    heads_cmd = [
        "git",
        "--git-dir",
        str(common_git_dir),
        "for-each-ref",
        "--format=%(refname:lstrip=2)\t%(objectname)",
        "refs/heads",
    ]
    heads_proc = subprocess.run(
        heads_cmd, capture_output=True, text=True, check=False
    )
    for branch_name, sha in _parse_tab_pairs(heads_proc.stdout):
        names.add(branch_name)
        shas.add(sha)

    cfg_cmd = [
        "git",
        "--git-dir",
        str(common_git_dir),
        "config",
        "--get-regexp",
        "--local",
        r"^branch\..*\.merge$",
    ]
    cfg_proc = subprocess.run(
        cfg_cmd, capture_output=True, text=True, check=False
    )
    for line in cfg_proc.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            _, merge_ref = parts
            names.add(merge_ref.removeprefix("refs/heads/"))
    return names, shas


def _get_protected_remote_targets(
    common_git_dir: Path,
) -> tuple[set[str], set[str]]:
    """Returns (protected_branch_names, protected_shas) across worktrees."""
    names, shas = _collect_local_heads_and_upstreams(common_git_dir)
    wt_proc = subprocess.run(
        [
            "git",
            "--git-dir",
            str(common_git_dir),
            "worktree",
            "list",
            "--porcelain",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in wt_proc.stdout.splitlines():
        if line.startswith("HEAD "):
            shas.add(line.removeprefix("HEAD ").strip())
        elif line.startswith("branch "):
            branch_ref = line.removeprefix("branch ").strip()
            names.add(branch_ref.removeprefix("refs/heads/"))
    return names, shas


def analyze_prunable_remote_branches(
    common_git_dir: Path,
    config: GkOptimizerConfig,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Returns ((branch_name, sha) to prune, kept names) for origin/*."""
    all_branches = _list_remote_origin_branches_sorted(common_git_dir)
    protected_names, protected_shas = _get_protected_remote_targets(
        common_git_dir
    )
    windows = config.tags.keep_recent_by_pattern
    counts: dict[str, int] = dict.fromkeys(windows, 0)
    to_prune: list[tuple[str, str]] = []
    kept: list[str] = []

    for branch_name, sha in all_branches:
        matched_prefix = _match_window_prefix(branch_name, windows)
        if branch_name in protected_names or sha in protected_shas:
            kept.append(branch_name)
            if matched_prefix is not None:
                counts[matched_prefix] += 1
            continue
        if matched_prefix is None:
            kept.append(branch_name)
            continue

        limit = max(0, int(windows[matched_prefix]))
        if counts[matched_prefix] < limit:
            counts[matched_prefix] += 1
            kept.append(branch_name)
        else:
            to_prune.append((branch_name, sha))

    return to_prune, kept


def backup_pruned_refs(
    backup_file: Path,
    pruned_refs: list[tuple[str, str]],
    ref_prefix: str = "refs/tags/",
) -> None:
    """Appends pruned (ref_name, sha) entries to pre_install_refs.json."""
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if backup_file.is_file():
        loaded = json.loads(backup_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = {str(k): str(v) for k, v in loaded.items()}

    for ref_name, sha in pruned_refs:
        full_ref = (
            ref_name
            if ref_name.startswith("refs/")
            else f"{ref_prefix}{ref_name}"
        )
        if full_ref not in existing:
            existing[full_ref] = sha

    backup_file.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _delete_refs_and_pack(
    common_git_dir: Path,
    refs_to_prune: list[tuple[str, str]],
    ref_prefix: str,
    backup_file: Path | None,
) -> int:
    """Deletes refs under ref_prefix via update-ref and packs refs."""
    if not refs_to_prune:
        return 0
    if backup_file is not None:
        backup_pruned_refs(backup_file, refs_to_prune, ref_prefix=ref_prefix)

    stdin_lines = [
        f"delete {ref_prefix}{name} {sha}" for name, sha in refs_to_prune
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
    return len(refs_to_prune)


def prune_tags(
    common_git_dir: Path,
    tags_to_prune: list[tuple[str, str]],
    backup_file: Path | None = None,
) -> int:
    """Atomically deletes (N+1)th+ tags via git update-ref and packs refs."""
    return _delete_refs_and_pack(
        common_git_dir, tags_to_prune, "refs/tags/", backup_file
    )


def prune_remote_branches(
    common_git_dir: Path,
    branches_to_prune: list[tuple[str, str]],
    backup_file: Path | None = None,
) -> int:
    """Atomically deletes (N+1)th+ remote pattern branches under origin."""
    return _delete_refs_and_pack(
        common_git_dir,
        branches_to_prune,
        "refs/remotes/origin/",
        backup_file,
    )


def revert_tags(
    common_git_dir: Path,
    backup_file: Path,
) -> int:
    """Restores pruned tags and remote refs via zero-OID create CAS."""
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
            "refs/remotes",
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
