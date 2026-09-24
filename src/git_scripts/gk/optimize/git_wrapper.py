"""GitKraken `selectedGitPath` wrapper.

Scrubs `LD_PRELOAD` before invoking `/usr/bin/git` and filters remote tag
operations (`ls-remote --tags`, `fetch`) to the configured retention window.
"""

import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REAL_GIT = "/usr/bin/git"
# Clear LD_PRELOAD so child git processes do not inherit the Electron shim.
os.environ.pop("LD_PRELOAD", None)


def _natural_key(tag_name: str) -> tuple[int | str, ...]:
    """Tokenizes numeric segments as integers for natural version sorting."""
    parts = re.split(r"(\d+)", tag_name)
    return tuple(int(p) if p.isdigit() else p for p in parts)


def _parse_yaml_with_pyyaml(raw_text: str) -> dict[str, int] | None:
    """Parses `tags.keep_recent_by_pattern` using PyYAML when available."""
    if yaml is None:
        return None
    try:
        data = yaml.safe_load(raw_text) or {}
        windows = data.get("tags", {}).get("keep_recent_by_pattern")
        if isinstance(windows, dict):
            return {str(k): int(v) for k, v in windows.items()}
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _parse_keep_recent_kv(stripped: str) -> tuple[str, int] | None:
    """Parses a `pattern: count` line inside `keep_recent_by_pattern:`."""
    if ":" not in stripped:
        return None
    key_raw, val_raw = stripped.split(":", 1)
    key = key_raw.strip().strip("'\"")
    val_str = val_raw.split("#", 1)[0].strip()
    if key and val_str.lstrip("-").isdigit():
        return key, int(val_str)
    return None


def _parse_simple_keep_recent_yaml(raw_text: str) -> dict[str, int] | None:
    """Parses `tags.keep_recent_by_pattern` with a stdlib fallback."""
    pyyaml_result = _parse_yaml_with_pyyaml(raw_text)
    if pyyaml_result is not None:
        return pyyaml_result

    parsed: dict[str, int] = {}
    in_keep_block = False
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("keep_recent_by_pattern:"):
            in_keep_block = True
            continue
        if not in_keep_block:
            continue
        if not line.startswith((" ", "\t")) or (
            stripped.endswith(":") and ":" not in stripped[:-1]
        ):
            break
        kv = _parse_keep_recent_kv(stripped)
        if kv is not None:
            parsed[kv[0]] = kv[1]
    return parsed or None


def _load_rolling_windows() -> dict[str, int]:
    """Loads tag retention windows from repo or user `config.yaml`."""
    default_windows = {"candidate/*": 5, "release/*": 5, "platform/*": 5}
    res = subprocess.run(
        [REAL_GIT, "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    candidates: list[Path] = []
    if res.returncode == 0 and res.stdout.strip():
        common_dir = Path(res.stdout.strip()).resolve()
        candidates.append(common_dir / "gk-optimizer" / "config.yaml")
    candidates.append(
        Path.home() / ".config" / "gitkraken-optimizer" / "config.yaml"
    )
    for cfg_path in candidates:
        try:
            if cfg_path.is_file():
                raw_text = cfg_path.read_text(encoding="utf-8")
                windows = _parse_simple_keep_recent_yaml(raw_text)
                if windows:
                    return windows
        except OSError:
            continue
    return default_windows


def _get_local_tag_ranks() -> dict[str, int]:
    """Ranks locally present tags newest-first by `-creatordate`."""
    res = subprocess.run(
        [
            REAL_GIT,
            "for-each-ref",
            "--sort=-creatordate",
            "--sort=-v:refname",
            "--format=%(refname:short)",
            "refs/tags",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        return {}
    return {
        line.strip(): idx
        for idx, line in enumerate(res.stdout.splitlines())
        if line.strip()
    }


def _compute_kept_by_prefix(
    entries: list[tuple[str, str, str]],
    windows: dict[str, int],
    local_ranks: dict[str, int],
) -> dict[str, set[str]]:
    """Selects the top `limit` tags per pattern (local rank, then natural)."""
    prefix_tags: dict[str, set[str]] = {p: set() for p in windows}
    for _, tag_name, matched_prefix in entries:
        if matched_prefix and tag_name:
            prefix_tags[matched_prefix].add(tag_name)

    kept_by_prefix: dict[str, set[str]] = {}
    for prefix, names in prefix_tags.items():
        limit = max(0, int(windows.get(prefix, 5)))
        local_list = sorted(
            (n for n in names if n in local_ranks),
            key=lambda n: local_ranks[n],
        )
        remote_list = sorted(
            (n for n in names if n not in local_ranks),
            key=_natural_key,
            reverse=True,
        )
        kept_by_prefix[prefix] = set((local_list + remote_list)[:limit])
    return kept_by_prefix


def _filter_ls_remote_tags(raw_stdout: str) -> str:
    """Filters `git ls-remote --tags` output, pairing `^{}` peeled refs."""
    windows = _load_rolling_windows()
    entries: list[tuple[str, str, str]] = []
    for line in raw_stdout.splitlines():
        if "\trefs/tags/" not in line:
            entries.append((line, "", ""))
            continue
        _, ref = line.split("\t", 1)
        base_ref = ref.removesuffix("^{}")
        tag_name = base_ref[len("refs/tags/") :]
        matched_prefix = next(
            (p for p in windows if fnmatch.fnmatchcase(tag_name, p)),
            "",
        )
        entries.append((line, tag_name, matched_prefix))

    kept_by_prefix = _compute_kept_by_prefix(
        entries, windows, _get_local_tag_ranks()
    )
    out_lines = [
        line
        for line, tag_name, matched_prefix in entries
        if not matched_prefix
        or tag_name in kept_by_prefix.get(matched_prefix, set())
    ]
    return "\n".join(out_lines) + ("\n" if out_lines else "")


def _rewrite_fetch_args(args: list[str]) -> list[str]:
    """Strips `--tags`/`-t` and injects `--no-tags` on `git fetch` calls."""
    if "fetch" not in args:
        return args
    cleaned = [a for a in args if a not in ("--tags", "-t")]
    if "--no-tags" not in cleaned:
        fetch_idx = cleaned.index("fetch")
        cleaned.insert(fetch_idx + 1, "--no-tags")
    return cleaned


def main() -> None:
    """Intercepts `ls-remote --tags` and `fetch`, passing others via execv."""
    args = sys.argv[1:]
    if "ls-remote" in args and ("--tags" in args or "-t" in args):
        proc = subprocess.run(
            [REAL_GIT, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        if proc.returncode == 0:
            sys.stdout.write(_filter_ls_remote_tags(proc.stdout))
        else:
            sys.stdout.write(proc.stdout)
        sys.exit(proc.returncode)
    rewritten = _rewrite_fetch_args(args)
    os.execv(REAL_GIT, [REAL_GIT, *rewritten])


if __name__ == "__main__":
    main()
