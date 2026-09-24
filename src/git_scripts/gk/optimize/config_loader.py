"""YAML configuration loader and symlink installer for git-gk-optimize."""

from pathlib import Path

import yaml

from git_scripts.gk.optimize.models import GkOptimizerConfig


def get_default_config_path() -> Path:
    """Returns the repository-bundled default config.yaml path."""
    return Path(__file__).resolve().parent / "config.yaml"


def get_user_config_path(home_dir: Path | None = None) -> Path:
    """Returns ~/.config/gitkraken-optimizer/config.yaml."""
    base = home_dir if home_dir is not None else Path.home()
    return base / ".config" / "gitkraken-optimizer" / "config.yaml"


def get_repo_config_path(common_git_dir: Path) -> Path:
    """Returns <common-git-dir>/gk-optimizer/config.yaml."""
    return common_git_dir / "gk-optimizer" / "config.yaml"


def read_config(
    config_path: Path | None = None,
    keep_recent_override: int | None = None,
) -> GkOptimizerConfig:
    """Reads and validates YAML configuration, applying optional overrides."""
    effective_path = (
        config_path
        if (config_path is not None and config_path.is_file())
        else get_default_config_path()
    )
    if effective_path.is_file():
        raw = yaml.safe_load(effective_path.read_text(encoding="utf-8")) or {}
        config = GkOptimizerConfig.model_validate(raw)
    else:
        config = GkOptimizerConfig()

    if keep_recent_override is not None:
        updated_windows = dict.fromkeys(
            config.tags.keep_recent_by_pattern, keep_recent_override
        )
        config = config.model_copy(
            update={
                "tags": config.tags.model_copy(
                    update={"keep_recent_by_pattern": updated_windows}
                )
            }
        )
    return config


def _replace_with_symlink(target: Path, dest_path: Path) -> None:
    """Replaces `dest_path` with a symlink to `target.resolve()`."""
    resolved_target = target.resolve()
    if dest_path.is_symlink() and dest_path.resolve() == resolved_target:
        return
    if dest_path.is_symlink() or dest_path.exists():
        dest_path.unlink()
    dest_path.symlink_to(resolved_target)


def write_config(
    config: GkOptimizerConfig,
    dest_path: Path,
    source_path: Path | None = None,
) -> None:
    """Symlinks `dest_path` to `config.yaml`, or writes YAML if overridden."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    bundled = get_default_config_path()
    candidate = (
        source_path
        if (source_path is not None and source_path.is_file())
        else bundled
    )
    if candidate.is_file() and read_config(candidate) == config:
        _replace_with_symlink(candidate, dest_path)
        return
    if dest_path.is_symlink():
        dest_path.unlink()
    payload = config.model_dump(mode="json")
    header = (
        "# git-gk-optimize configuration\n"
        "# Controls rolling tag windows and NSFW"
        " (Node Sentinel File Watcher) ignores\n"
    )
    yaml_text = yaml.safe_dump(payload, sort_keys=False)
    dest_path.write_text(header + yaml_text, encoding="utf-8")
