"""CMake and C compiler builder for the GitKraken LD_PRELOAD shim."""

import os
import shutil
import subprocess
from pathlib import Path


def get_src_dir() -> Path:
    """Returns the directory containing CMakeLists.txt and the C shim."""
    return Path(__file__).resolve().parent / "csrc"


def get_project_root() -> Path:
    """Returns the root directory of the git-scripts repository."""
    return Path(__file__).resolve().parents[4]


def _resolve_build_env(project_root: Path) -> dict[str, str]:
    """Prepends Pixi environment binaries to PATH for CMake/Ninja builds."""
    env = dict(os.environ)
    pixi_bin = project_root / ".pixi" / "envs" / "default" / "bin"
    if pixi_bin.is_dir():
        env["PATH"] = f"{pixi_bin}:{env.get('PATH', '')}"
    return env


def build_shim(
    dest_dir: Path,
    project_root: Path | None = None,
) -> Path:
    """Builds and installs `libgk_preload_shim.so` via CMake (or `cc`)."""
    root = project_root if project_root is not None else get_project_root()
    src_dir = get_src_dir()
    build_dir = root / "build" / "gk_shim"
    try:
        build_dir.mkdir(parents=True, exist_ok=True)
        probe = build_dir / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        build_dir = dest_dir / "_cmake_build"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_so = dest_dir / "libgk_preload_shim.so"

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
        subprocess.run(
            [
                cmake_bin,
                "--install",
                str(build_dir),
                "--prefix",
                str(dest_dir),
            ],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
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
            str(src_dir / "gk_preload_shim.c"),
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
