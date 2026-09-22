"""CMake builder and XDG launcher/wrapper installer for git-gk-optimize."""

import json
import os
import shutil
import subprocess
from pathlib import Path


def get_src_dir() -> Path:
    """Returns the directory with CMakeLists.txt and gk_nsfw_nofollow.c."""
    return Path(__file__).resolve().parent / "csrc"


def get_wrapper_template_path() -> Path:
    """Returns the standalone stdlib gitkraken_git_wrapper.py path."""
    return Path(__file__).resolve().parent / "gitkraken_git_wrapper.py"


def get_project_root() -> Path:
    """Returns the root of the git-scripts repository."""
    return Path(__file__).resolve().parents[4]


def _resolve_build_env(project_root: Path) -> dict[str, str]:
    """Prepends Pixi environment binaries to PATH for CMake/Ninja builds."""
    env = dict(os.environ)
    pixi_bin = project_root / ".pixi" / "envs" / "default" / "bin"
    if pixi_bin.is_dir():
        env["PATH"] = f"{pixi_bin}:{env.get('PATH', '')}"
    return env


def build_and_install_shim_so(
    dest_dir: Path,
    project_root: Path | None = None,
) -> Path:
    """Builds libgk_nsfw_nofollow.so via CMake + Ninja and installs it."""
    root = project_root if project_root is not None else get_project_root()
    src_dir = get_src_dir()
    build_dir = root / "build" / "gk_shim"
    if not os.access(root, os.W_OK):
        build_dir = dest_dir / "_cmake_build"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_so = dest_dir / "libgk_nsfw_nofollow.so"

    env = _resolve_build_env(root)
    cmake_bin = shutil.which("cmake", path=env.get("PATH"))
    ninja_bin = shutil.which("ninja", path=env.get("PATH"))

    if cmake_bin is not None:
        cache_file = build_dir / "CMakeCache.txt"
        if cache_file.is_file() and str(src_dir) not in cache_file.read_text(
            encoding="utf-8", errors="ignore"
        ):
            shutil.rmtree(build_dir, ignore_errors=True)
        generator_args = ["-G", "Ninja"] if ninja_bin is not None else []
        subprocess.run(
            [
                cmake_bin,
                "--fresh",
                "-S",
                str(src_dir),
                "-B",
                str(build_dir),
                *generator_args,
                "-DCMAKE_BUILD_TYPE=Release",
            ],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [cmake_bin, "--build", str(build_dir)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        built_so = build_dir / "libgk_nsfw_nofollow.so"
        shutil.copy2(built_so, target_so)
        return target_so

    cc_bin = (
        env.get("CC")
        or shutil.which("gcc", path=env.get("PATH"))
        or shutil.which("cc", path=env.get("PATH"))
    )
    if cc_bin is None:
        msg = "Neither cmake nor a C compiler (gcc/cc) was found in PATH."
        raise RuntimeError(msg)
    subprocess.run(
        [
            cc_bin,
            "-shared",
            "-fPIC",
            "-O2",
            "-Wall",
            "-Wextra",
            str(src_dir / "gk_nsfw_nofollow.c"),
            "-o",
            str(target_so),
            "-ldl",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return target_so


def write_gitkraken_git_wrapper(dest_dir: Path) -> Path:
    """Writes the gitkraken-git selectedGitPath wrapper executable."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = dest_dir / "gitkraken-git"
    body = get_wrapper_template_path().read_text(encoding="utf-8")
    if not body.startswith("#!"):
        body = "#!/usr/bin/env python3\n" + body
    wrapper_path.write_text(body, encoding="utf-8")
    wrapper_path.chmod(0o755)
    return wrapper_path


def register_watched_repo(dest_dir: Path, common_git_dir: Path) -> Path:
    """Appends common_git_dir to watched_repos.json without duplicates."""
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
    """Removes common_git_dir from watched_repos.json; True if empty."""
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


def write_gitkraken_launcher_and_desktop(
    dest_dir: Path,
    common_git_dir: Path,
    ignored_dirs: list[str],
    applications_dir: Path | None = None,
    project_root: Path | None = None,
) -> tuple[Path, Path]:
    """Creates gitkraken-launcher and applications/gitkraken.desktop."""
    root = project_root if project_root is not None else get_project_root()
    dest_dir.mkdir(parents=True, exist_ok=True)
    register_watched_repo(dest_dir, common_git_dir)
    launcher_path = dest_dir / "gitkraken-launcher"
    shim_so = dest_dir / "libgk_nsfw_nofollow.so"
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
