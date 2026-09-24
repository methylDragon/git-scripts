"""GitKraken XDG launcher, git wrapper, and watched-repo registry writer."""

import json
import os
from pathlib import Path

from git_scripts.gk.optimize.shim_builder import get_project_root


def get_wrapper_template_path() -> Path:
    """Returns the standalone stdlib git_wrapper.py template."""
    return Path(__file__).resolve().parent / "git_wrapper.py"


def write_git_wrapper(dest_dir: Path) -> Path:
    """Installs the `gitkraken-git` wrapper used for `selectedGitPath`."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = dest_dir / "gitkraken-git"
    body = get_wrapper_template_path().read_text(encoding="utf-8")
    if not body.startswith("#!"):
        body = "#!/usr/bin/env python3\n" + body
    wrapper_path.write_text(body, encoding="utf-8")
    wrapper_path.chmod(0o755)
    return wrapper_path


def register_watched_repo(dest_dir: Path, common_git_dir: Path) -> Path:
    """Adds `common_git_dir` to `watched_repos.json` for `watch-daemon`."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    repos_file = dest_dir / "watched_repos.json"
    existing: list[str] = []
    if repos_file.is_file():
        data = json.loads(repos_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("repos"), list):
            existing = [str(p) for p in data["repos"] if p]
    resolved = str(common_git_dir.resolve())
    if resolved not in existing:
        existing.append(resolved)
    repos_file.write_text(
        json.dumps({"repos": existing}, indent=2) + "\n",
        encoding="utf-8",
    )
    return repos_file


def unregister_watched_repo(dest_dir: Path, common_git_dir: Path) -> bool:
    """Removes `common_git_dir` from `watched_repos.json`; True if empty."""
    repos_file = dest_dir / "watched_repos.json"
    if not repos_file.is_file():
        return True
    resolved = str(common_git_dir.resolve())
    data = json.loads(repos_file.read_text(encoding="utf-8"))
    raw_list = data.get("repos", []) if isinstance(data, dict) else []
    remaining = [str(p) for p in raw_list if p and str(p) != resolved]
    if remaining:
        repos_file.write_text(
            json.dumps({"repos": remaining}, indent=2) + "\n",
            encoding="utf-8",
        )
        return False
    repos_file.unlink()
    return True


def write_gitkraken_launcher(
    dest_dir: Path,
    common_git_dir: Path,
    ignored_dirs: list[str],
    applications_dir: Path | None = None,
    project_root: Path | None = None,
) -> tuple[Path, Path]:
    """Writes `gitkraken-launcher` and the XDG `gitkraken.desktop` entry.

    The launcher re-applies `selectedGitPath` before startup (GitKraken
    overwrites profile files on exit) and spawns `watch-daemon --gk-pid "$$"`
    prior to `exec` so PID `$$` stays bound to the Electron process.
    """
    root = project_root if project_root is not None else get_project_root()
    dest_dir.mkdir(parents=True, exist_ok=True)
    launcher_path = dest_dir / "gitkraken-launcher"
    shim_so = dest_dir / "libgk_preload_shim.so"
    ignored_colon = ":".join(ignored_dirs)
    git_gk_optimize_bin = root / "bin" / "git-gk-optimize"
    if git_gk_optimize_bin.is_file() and not os.access(
        git_gk_optimize_bin, os.X_OK
    ):
        try:
            git_gk_optimize_bin.chmod(0o755)
        except OSError:
            pass
    daemon_cmd = (
        f'"{git_gk_optimize_bin}" watch-daemon "{common_git_dir}"'
        ' --gk-pid "$$" >/dev/null 2>&1 &'
    )

    apps_dir = (
        applications_dir
        if applications_dir is not None
        else Path.home() / ".local" / "share" / "applications"
    )
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = apps_dir / "gitkraken.desktop"

    gk_git_wrapper = dest_dir / "gitkraken-git"
    launcher_script = f"""#!/usr/bin/env bash
set -e
python3 - "{gk_git_wrapper}" <<'PYEOF' || true
import json, pathlib, sys
gk_git = sys.argv[1]
profiles = pathlib.Path.home() / ".gitkraken" / "profiles"
if profiles.is_dir():
    for p in profiles.glob("*/profile"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("selectedGitPath") != gk_git:
                d["selectedGitPath"] = gk_git
                p.write_text(json.dumps(d, indent=2), encoding="utf-8")
        except Exception:
            pass
PYEOF
if [ -f "{git_gk_optimize_bin}" ]; then
    {daemon_cmd}
fi
export BAMF_DESKTOP_FILE_HINT="{desktop_path}"
export UV_THREADPOOL_SIZE=64
export GK_IGNORED_DIRS="{ignored_colon}"
export LD_PRELOAD="{shim_so}"
exec /usr/share/gitkraken/gitkraken "$@"
"""
    launcher_path.write_text(launcher_script, encoding="utf-8")
    launcher_path.chmod(0o755)

    desktop_content = f"""[Desktop Entry]
Name=GitKraken (Optimized)
Comment=GitKraken Desktop with NSFW (Node Sentinel File Watcher) & tag fixes
GenericName=Git Client
Exec={launcher_path} %U
Icon=/usr/share/pixmaps/gitkraken.png
Type=Application
StartupNotify=true
StartupWMClass=gitkraken
Categories=GNOME;GTK;Development;RevisionControl;
MimeType=text/plain;x-scheme-handler/gitkraken;
"""
    desktop_path.write_text(desktop_content, encoding="utf-8")
    return launcher_path, desktop_path
