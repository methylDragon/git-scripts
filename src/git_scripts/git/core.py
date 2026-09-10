"""Git subprocess wrappers for core execution."""

import shlex
import subprocess


class GitExecutionError(Exception):
    """Custom exception for git subprocess errors."""

    pass


def run_cmd(
    cmd: list[str],
    cwd: str | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> str:
    """Executes a subprocess command and returns stripped stdout."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            capture_output=capture_output,
            text=True,
        )
        return result.stdout.strip() if result.stdout else ""
    except subprocess.CalledProcessError as e:
        cmd_str = shlex.join(cmd)
        err_out = e.stderr.strip() if getattr(e, "stderr", None) else str(e)
        raise GitExecutionError(
            f"Command failed: {cmd_str}\nError: {err_out}"
        ) from e
