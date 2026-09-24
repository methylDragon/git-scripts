"""Command orchestrator for git-gk-optimize (install, verify, uninstall)."""

# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals

import json
import subprocess
from pathlib import Path

from git_scripts.gk.optimize.config_loader import (
    get_repo_config_path,
    get_user_config_path,
    read_config,
    write_config,
)
from git_scripts.gk.optimize.gitkraken_launcher import (
    register_watched_repo,
    unregister_watched_repo,
    write_git_wrapper,
    write_gitkraken_launcher,
)
from git_scripts.gk.optimize.models import (
    GkExpectMode,
    GkOptimizeResult,
    GkVerifyResult,
)
from git_scripts.gk.optimize.shim_builder import build_shim
from git_scripts.gk.optimize.state_manager import (
    apply_fetch_refspecs,
    apply_gk_settings,
    get_state_path,
    read_state,
    revert_fetch_refspecs,
    revert_gk_settings,
    write_state,
)
from git_scripts.gk.optimize.tag_pruner import (
    analyze_prunable_tags,
    prune_tags,
    revert_tags,
)
from git_scripts.gk.optimize.worktree_watcher import (
    execute_watch_daemon,
    record_prune_marker,
)
from git_scripts.ui import UI

__all__ = [
    "GkExpectMode",
    "execute_gk_install",
    "execute_gk_uninstall",
    "execute_gk_verify",
    "execute_watch_daemon",
]


def resolve_repo_and_common_git_dir(
    repo_path: str | Path,
) -> tuple[Path, Path]:
    """Resolves the working tree root and shared common .git directory."""
    target = Path(repo_path).resolve()
    top_proc = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    common_proc = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    top_dir = Path(top_proc.stdout.strip()).resolve()
    raw_common = Path(common_proc.stdout.strip())
    common_dir = (
        raw_common.resolve()
        if raw_common.is_absolute()
        else (target / raw_common).resolve()
    )
    return top_dir, common_dir


def _close_gitkraken_if_requested(close_gitkraken: bool) -> None:
    """Politely terminates running GitKraken processes if requested."""
    if not close_gitkraken:
        return
    subprocess.run(
        ["pkill", "-f", "/usr/share/gitkraken/gitkraken"],
        check=False,
        capture_output=True,
    )


def execute_gk_install(
    repo_path: str | Path,
    ui: UI,
    config_path: Path | None = None,
    keep_recent_override: int | None = None,
    close_gitkraken: bool = False,
    home_dir: Path | None = None,
    gk_root: Path | None = None,
) -> GkOptimizeResult:
    """Installs all 3 GitKraken worktree optimizations and CAS state."""
    base_home = home_dir if home_dir is not None else Path.home()
    default_gk = base_home / ".gitkraken"
    effective_gk_root = gk_root if gk_root is not None else default_gk
    opt_home_dir = base_home / ".config" / "gitkraken-optimizer"
    apps_dir = base_home / ".local" / "share" / "applications"

    _close_gitkraken_if_requested(close_gitkraken)
    repo_root, common_git_dir = resolve_repo_and_common_git_dir(repo_path)

    user_cfg_file = (
        config_path
        if config_path is not None
        else get_user_config_path(base_home)
    )
    config = read_config(user_cfg_file, keep_recent_override)
    write_config(
        config,
        get_user_config_path(base_home),
        source_path=user_cfg_file,
    )
    write_config(
        config,
        get_repo_config_path(common_git_dir),
        source_path=user_cfg_file,
    )

    shim_so = build_shim(opt_home_dir)
    gk_git = write_git_wrapper(opt_home_dir)
    register_watched_repo(opt_home_dir, common_git_dir)
    _, desktop_path = write_gitkraken_launcher(
        dest_dir=opt_home_dir,
        common_git_dir=common_git_dir,
        ignored_dirs=config.watcher.ignored_dirs,
        applications_dir=apps_dir,
    )

    state = read_state(common_git_dir)
    apply_fetch_refspecs(
        common_git_dir, config.tags.blocked_fetch_patterns, state
    )

    to_prune, kept = analyze_prunable_tags(common_git_dir, config)
    backup_refs = common_git_dir / "gk-optimizer" / "pre_install_refs.json"
    pruned_count = prune_tags(common_git_dir, to_prune, backup_refs)
    record_prune_marker(common_git_dir)

    cleaned_rs = apply_gk_settings(
        gk_root=effective_gk_root,
        gitkraken_git_path=gk_git,
        kept_tags=set(kept),
        state=state,
    )
    write_state(common_git_dir, state)

    details = [
        (
            "Built & installed preload runtime shim"
            f" (NSFW & UI patcher): {shim_so}"
        ),
        f"Installed desktop launcher override: {desktop_path}",
        (
            f"Pruned {pruned_count} historical CI tags; kept {len(kept)} tags"
            " (100% normal + rolling windows)"
        ),
        f"Shrunk {cleaned_rs} GitKraken repoSettings JSON file(s)",
    ]
    for msg in details:
        ui.print(f"[green]✓[/green] {msg}")

    return GkOptimizeResult(
        success=True,
        repo_root=str(repo_root),
        common_git_dir=str(common_git_dir),
        pruned_tags_count=pruned_count,
        kept_tags_count=len(kept),
        shim_so_path=str(shim_so),
        desktop_entry_path=str(desktop_path),
        details=details,
    )


def execute_gk_uninstall(
    repo_path: str | Path,
    ui: UI,
    close_gitkraken: bool = False,
    home_dir: Path | None = None,
) -> GkOptimizeResult:
    """Reverts GitKraken optimizations using Compare-And-Swap safely."""
    base_home = home_dir if home_dir is not None else Path.home()
    opt_home_dir = base_home / ".config" / "gitkraken-optimizer"
    apps_rel = Path(".local/share/applications/gitkraken.desktop")
    desktop_path = base_home / apps_rel

    _close_gitkraken_if_requested(close_gitkraken)
    repo_root, common_git_dir = resolve_repo_and_common_git_dir(repo_path)

    state_file = get_state_path(common_git_dir)
    if not state_file.is_file():
        msg = "No git-gk-optimize saved state found; nothing to uninstall."
        ui.print(f"[yellow]! {msg}[/yellow]")
        return GkOptimizeResult(
            success=False,
            repo_root=str(repo_root),
            common_git_dir=str(common_git_dir),
            pruned_tags_count=0,
            kept_tags_count=0,
            shim_so_path=str(opt_home_dir / "libgk_preload_shim.so"),
            desktop_entry_path=str(desktop_path),
            details=[msg],
        )

    state = read_state(common_git_dir)
    revert_fetch_refspecs(common_git_dir, state)
    revert_gk_settings(state)

    backup_refs = common_git_dir / "gk-optimizer" / "pre_install_refs.json"
    restored_count = revert_tags(common_git_dir, backup_refs)

    no_repos_left = unregister_watched_repo(opt_home_dir, common_git_dir)
    if no_repos_left and desktop_path.is_file():
        desktop_path.unlink()

    for artifact in (
        state_file,
        backup_refs,
        common_git_dir / "gk-optimizer" / "last_tag_prune.json",
        get_repo_config_path(common_git_dir),
    ):
        if artifact.is_symlink() or artifact.is_file():
            artifact.unlink()

    details = [
        f"Restored {restored_count} pruned tag refs via zero-OID CAS",
        (
            "Reverted GitKraken profile & repoSettings via CAS"
            " (preserving post-install edits)"
        ),
        f"Removed XDG desktop override: {desktop_path}",
    ]
    for msg in details:
        ui.print(f"[green]✓[/green] {msg}")

    return GkOptimizeResult(
        success=True,
        repo_root=str(repo_root),
        common_git_dir=str(common_git_dir),
        pruned_tags_count=0,
        kept_tags_count=restored_count,
        shim_so_path=str(opt_home_dir / "libgk_preload_shim.so"),
        desktop_entry_path=str(desktop_path),
        details=details,
    )


def execute_gk_verify(
    repo_path: str | Path,
    ui: UI,
    expect: GkExpectMode = GkExpectMode.INSTALLED,
    home_dir: Path | None = None,
    gk_root: Path | None = None,
) -> GkVerifyResult:
    """Verifies whether git-gk-optimize is cleanly installed or uninstalled."""
    base_home = home_dir if home_dir is not None else Path.home()
    default_gk = base_home / ".gitkraken"
    effective_gk_root = gk_root if gk_root is not None else default_gk
    opt_home_dir = base_home / ".config" / "gitkraken-optimizer"
    apps_rel = Path(".local/share/applications/gitkraken.desktop")
    desktop_path = base_home / apps_rel

    _, common_git_dir = resolve_repo_and_common_git_dir(repo_path)
    shim_so = opt_home_dir / "libgk_preload_shim.so"
    gk_git = opt_home_dir / "gitkraken-git"
    state_file = get_state_path(common_git_dir)

    cfg_file = get_repo_config_path(common_git_dir)
    config = read_config(cfg_file if cfg_file.is_file() else None)
    to_prune, _ = analyze_prunable_tags(common_git_dir, config)

    checks: dict[str, bool] = {}
    if expect == GkExpectMode.INSTALLED:
        checks["shim_so_built (libgk_preload_shim.so)"] = shim_so.is_file()
        checks["gitkraken_git_executable"] = gk_git.is_file()
        dt_ok = desktop_path.is_file()
        dt_text = desktop_path.read_text(encoding="utf-8") if dt_ok else ""
        checks["desktop_override_present"] = "GitKraken (Optimized)" in dt_text
        checks["saved_state_present"] = state_file.is_file()
        checks["rolling_tag_window_enforced"] = len(to_prune) == 0
        profile_files = (
            list((effective_gk_root / "profiles").glob("*/profile"))
            if (effective_gk_root / "profiles").is_dir()
            else []
        )
        if profile_files:
            checks["profile_selected_git_path_set"] = all(
                json.loads(p.read_text(encoding="utf-8")).get(
                    "selectedGitPath",
                )
                == str(gk_git)
                for p in profile_files
            )
    else:
        checks["desktop_override_removed"] = not desktop_path.exists()
        checks["saved_state_removed"] = not state_file.exists()

    failures = [name for name, ok in checks.items() if not ok]
    passed = len(failures) == 0
    for name, ok in checks.items():
        mark = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        ui.print(f"{mark} {name}")

    return GkVerifyResult(passed=passed, checks=checks, failures=failures)
