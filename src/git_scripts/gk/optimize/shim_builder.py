"""CMake/C builder and app.asar compatibility checker for GitKraken."""

import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any, BinaryIO

from git_scripts.gk.optimize.models import AsarCompatibilityResult

DEFAULT_ASAR_PATH = Path("/usr/share/gitkraken/resources/app.asar")
SUPPORTED_GK_VERSIONS = "12.4.x (tested on v12.4.0)"

ASAR_PATCH_SPECS: tuple[tuple[str, tuple[str, ...], bytes], ...] = (
    (
        "styles.css (detail-panel flexbox)",
        ("src", "css", "styles.css"),
        b"transition:var(--expand-detail-panel-transition)",
    ),
    (
        "base.jsonc (detail-panel transition)",
        ("src", "main", "static", "themeBases", "base.jsonc"),
        b'"expand-detail-panel-transition": "flex-grow 250ms ease-in-out"',
    ),
    (
        "render.bundle.js (cached tab-switch refresh)",
        (
            "src",
            "render",
            "static",
            "entryPoints",
            "main",
            "render.bundle.js",
        ),
        b'blocking:!0,callSource:"RepoSagas.openRepo (usingReduxCache)"',
    ),
)

_ASAR_HEADER_PICKLE_SIZE = 4
_ASAR_MAX_HEADER_BYTES = 64 * 1024 * 1024
_VERSION_RE = re.compile(rb'"version"\s*:\s*"([^"]+)"')


def _read_asar_header(handle: BinaryIO) -> tuple[int, dict[str, Any]] | None:
    """Parses the Electron ASAR JSON directory tree if present at offset 0."""
    handle.seek(0)
    prefix = handle.read(16)
    if len(prefix) < 16:
        return None
    pickle_sz, header_sz, _, json_len = struct.unpack("<IIII", prefix)
    if (
        pickle_sz != _ASAR_HEADER_PICKLE_SIZE
        or json_len == 0
        or json_len > header_sz
        or header_sz > _ASAR_MAX_HEADER_BYTES
    ):
        return None
    raw_json = handle.read(json_len)
    if len(raw_json) < json_len:
        return None
    try:
        parsed = json.loads(raw_json.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return (8 + header_sz, parsed) if isinstance(parsed, dict) else None


def _read_asar_entry_bytes(
    handle: BinaryIO,
    data_offset: int,
    header_tree: dict[str, Any],
    rel_path: tuple[str, ...],
) -> bytes | None:
    """Reads a single file entry from an indexed ASAR archive by path."""
    node: Any = header_tree
    for segment in rel_path:
        files_map = node.get("files") if isinstance(node, dict) else None
        if not isinstance(files_map, dict) or segment not in files_map:
            return None
        node = files_map[segment]
    if (
        not isinstance(node, dict)
        or "offset" not in node
        or "size" not in node
    ):
        return None
    try:
        offset = int(node["offset"])
        size = int(node["size"])
    except (TypeError, ValueError):
        return None
    if offset < 0 or size < 0:
        return None
    handle.seek(data_offset + offset)
    return handle.read(size)


def _extract_indexed_asar_version(
    handle: BinaryIO,
    data_offset: int,
    header_tree: dict[str, Any],
) -> str | None:
    """Reads `package.json` from the ASAR index and returns `version`."""
    pkg_bytes = _read_asar_entry_bytes(
        handle, data_offset, header_tree, ("package.json",)
    )
    if pkg_bytes is None:
        return None
    try:
        pkg_data = json.loads(pkg_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if isinstance(pkg_data, dict) and pkg_data.get("version"):
        return str(pkg_data["version"])
    return None


def _scan_indexed_asar(
    handle: BinaryIO,
    data_offset: int,
    header_tree: dict[str, Any],
) -> tuple[str | None, list[str], list[str]]:
    """Extracts version and checks patch needles using the ASAR index."""
    detected_version = _extract_indexed_asar_version(
        handle, data_offset, header_tree
    )
    matched: list[str] = []
    missing: list[str] = []
    for label, rel_path, needle in ASAR_PATCH_SPECS:
        entry_bytes = _read_asar_entry_bytes(
            handle, data_offset, header_tree, rel_path
        )
        if entry_bytes is not None and needle in entry_bytes:
            matched.append(label)
        else:
            missing.append(label)
    return detected_version, matched, missing


def _scan_raw_asar(
    handle: BinaryIO,
) -> tuple[str | None, list[str], list[str]]:
    """Extracts version and checks patch needles across a flat byte stream."""
    handle.seek(0)
    raw_bytes = handle.read()
    ver_match = _VERSION_RE.search(raw_bytes)
    detected_version = (
        ver_match.group(1).decode("utf-8", errors="ignore")
        if ver_match is not None
        else None
    )
    matched: list[str] = []
    missing: list[str] = []
    for label, _, needle in ASAR_PATCH_SPECS:
        if needle in raw_bytes:
            matched.append(label)
        else:
            missing.append(label)
    return detected_version, matched, missing


def _build_remediation_hint(
    asar_path: Path,
    detected_version: str | None,
    missing_patches: list[str],
) -> str:
    """Formats an actionable warning when app.asar patches do not match."""
    ver_label = (
        f"v{detected_version}" if detected_version else "unknown version"
    )
    missing_list = ", ".join(missing_patches)
    return (
        f"GitKraken {ver_label} at {asar_path} is missing expected app.asar"
        f" patch target(s): {missing_list}. Compatible versions:"
        f" {SUPPORTED_GK_VERSIONS} (unmatched patches safely no-op at"
        " runtime). Use a compatible GitKraken version or update the needle"
        " constants in src/git_scripts/gk/optimize/csrc/gk_preload_shim.c"
        " and src/git_scripts/gk/optimize/shim_builder.py."
    )


def verify_asar_compatibility(
    asar_path: Path = DEFAULT_ASAR_PATH,
) -> AsarCompatibilityResult:
    """Checks whether `app.asar` contains all expected preload shim needles."""
    all_labels = [label for label, _, _ in ASAR_PATCH_SPECS]
    if not asar_path.is_file():
        return AsarCompatibilityResult(
            compatible=False,
            asar_exists=False,
            detected_version=None,
            supported_versions=SUPPORTED_GK_VERSIONS,
            matched_patches=[],
            missing_patches=all_labels,
            remediation_hint=f"GitKraken archive not found at {asar_path}.",
        )

    with asar_path.open("rb") as handle:
        header_info = _read_asar_header(handle)
        if header_info is not None:
            data_offset, header_tree = header_info
            detected_version, matched, missing = _scan_indexed_asar(
                handle, data_offset, header_tree
            )
        else:
            detected_version, matched, missing = _scan_raw_asar(handle)

    compatible = len(missing) == 0
    hint = (
        None
        if compatible
        else _build_remediation_hint(asar_path, detected_version, missing)
    )
    return AsarCompatibilityResult(
        compatible=compatible,
        asar_exists=True,
        detected_version=detected_version,
        supported_versions=SUPPORTED_GK_VERSIONS,
        matched_patches=matched,
        missing_patches=missing,
        remediation_hint=hint,
    )


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
