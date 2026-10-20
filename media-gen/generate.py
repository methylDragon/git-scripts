#!/usr/bin/env python3
"""Script to run VHS tapes and generate verified GIFs."""

import argparse
import contextlib
import glob
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import questionary
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)


@dataclass(frozen=True)
class TapeExpectation:
    """Expected scenario name and terminal output markers for a VHS tape."""

    scenario: str
    expected_markers: tuple[str, ...]


TAPE_EXPECTATIONS: dict[str, TapeExpectation] = {
    "rebase_prefix.tape": TapeExpectation(
        scenario="rebase-prefix",
        expected_markers=(
            "BATCH SUMMARY",
            "Deleted Branches",
            "Local branches updated",
            "To /tmp/vhs-remote-rebase-prefix",
        ),
    ),
    "push_stack.tape": TapeExpectation(
        scenario="push-stack",
        expected_markers=(
            "Analyzing stack for 'demo/d-e-f-g-h-i'",
            "To /tmp/vhs-remote-push-stack",
        ),
    ),
    "push_prefix.tape": TapeExpectation(
        scenario="push-prefix",
        expected_markers=(
            "Scanning 'refs/heads/demo/*'",
            "To /tmp/vhs-remote-push-prefix",
        ),
    ),
    "prune_local.tape": TapeExpectation(
        scenario="prune-local",
        expected_markers=(
            "Found 3 orphaned local branches",
            "Pruning branches...",
            "Deleted branch demo/a-b-c",
        ),
    ),
    "prune_remote_prefix.tape": TapeExpectation(
        scenario="prune-remote",
        expected_markers=(
            "Found 1 obsolete remote branches",
            "Deleting 1 branches from origin...",
            "Remote cleanup complete.",
        ),
    ),
    "gh_align_pr_bases_and_sync_stacks.tape": TapeExpectation(
        scenario="gh-align",
        expected_markers=(
            "Branch Summary",
            "All PR operations completed successfully!",
            "Stack linked successfully!",
            "Final Alignment Summary",
        ),
    ),
    "evolve.tape": TapeExpectation(
        scenario="evolve",
        expected_markers=(
            "Found 2 stack tips",
            "EVOLVE SUMMARY",
            "All Done! (2 stacks evolved)",
            "Local branches updated/amended",
        ),
    ),
}


def _capture_tmux_pane(
    sock: str, pane: str, start_line: str | None = None
) -> str:
    """Capture text content from a tmux pane on the given socket."""
    cmd = ["tmux", "-S", sock, "capture-pane", "-p"]
    if start_line is not None:
        cmd.extend(["-S", start_line])
    cmd.extend(["-t", pane])
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False
    ).stdout


def _capture_and_verify_panes(
    scenario: str, expected_markers: tuple[str, ...]
) -> tuple[bool, str]:
    """Capture tmux panes after VHS finishes and verify expected markers."""
    sock = f"/tmp/vhs-tmux-{scenario}.sock"
    cmd_capture = _capture_tmux_pane(sock, "vhs_demo:0.2", start_line="-200")
    comment_capture = _capture_tmux_pane(sock, "vhs_demo:0.0")

    missing = [m for m in expected_markers if m not in cmd_capture]
    if "@" in comment_capture:
        missing.append("unparsed '@' marker in comment pane")
    return not missing, ", ".join(missing)


def _run_single_attempt(
    tape_file: str, project_root: Path
) -> tuple[bool, str]:
    """Pre-initialize scenario, run VHS, verify output, and clean up."""
    tape_name = Path(tape_file).name
    expectation = TAPE_EXPECTATIONS.get(tape_name)
    setup_script = project_root / "media-gen" / "setup_demo_repo.py"

    if expectation is None:
        try:
            res = subprocess.run(
                ["vhs", tape_file],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
        except (subprocess.TimeoutExpired, OSError) as err:
            return False, f"vhs execution failed: {err}"
        return res.returncode == 0, res.stderr.strip()

    scenario = expectation.scenario
    try:
        setup_res = subprocess.run(
            [
                sys.executable,
                str(setup_script),
                "--scenario",
                scenario,
                "--init-tmux",
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if setup_res.returncode != 0:
            err = setup_res.stderr.strip() or setup_res.stdout.strip()
            return False, f"setup_demo_repo failed: {err}"

        res = subprocess.run(
            ["vhs", tape_file],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if res.returncode != 0:
            err_text = res.stderr.strip() or "vhs exited with non-zero code"
            return False, err_text
        return _capture_and_verify_panes(
            scenario, expectation.expected_markers
        )
    except (subprocess.TimeoutExpired, OSError) as err:
        return False, f"execution failed: {err}"
    finally:
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            subprocess.run(
                [
                    sys.executable,
                    str(setup_script),
                    "--scenario",
                    scenario,
                    "--cleanup",
                ],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )


def run_vhs(
    tape_file: str,
    progress: Progress,
    task_id: TaskID,
    max_attempts: int = 2,
) -> tuple[str, bool, str]:
    """Execute vhs for a tape file with verification and retry."""
    project_root = Path(__file__).resolve().parent.parent
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            progress.update(
                task_id,
                description=(
                    f"[yellow]Retrying {Path(tape_file).name} "
                    f"(attempt {attempt}/{max_attempts})..."
                ),
            )
        ok, err_msg = _run_single_attempt(tape_file, project_root)
        if ok:
            progress.update(task_id, visible=False)
            return tape_file, True, ""
        last_err = err_msg

    progress.update(task_id, visible=False)
    return tape_file, False, last_err


def _select_tapes(
    all_tapes: list[str],
    *,
    run_all: bool,
    requested: list[str] | None = None,
) -> list[str]:
    """Return all tapes, matching requested tapes, or prompt interactively."""
    if requested:
        req_set = {Path(r).name for r in requested}
        matched = [
            t for t in all_tapes if Path(t).name in req_set or t in requested
        ]
        if not matched:
            sys.exit(f"No matching tapes found for: {', '.join(requested)}")
        return matched
    if run_all:
        return all_tapes
    if not sys.stdin.isatty():
        sys.exit("Non-interactive session: pass --all or --tape <name>.")

    choices = [
        questionary.Choice(title=Path(t).name, value=t) for t in all_tapes
    ]
    selected = questionary.checkbox(
        "Select which tapes to generate (Space to toggle, Enter to confirm):",
        choices=choices,
    ).ask()
    if not selected:
        print("No tapes selected. Exiting.")
        sys.exit(0)
    return selected


def _render_selected_tapes(
    selected_tapes: list[str], workers: int
) -> list[tuple[str, str]]:
    """Render selected VHS tapes in parallel and return any failures."""
    failures: list[tuple[str, str]] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=False,
    ) as progress:
        overall_task = progress.add_task(
            "[bold cyan]Rendering VHS Tapes...", total=len(selected_tapes)
        )

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [
                executor.submit(
                    run_vhs,
                    tape,
                    progress,
                    progress.add_task(
                        f"[yellow]Rendering {Path(tape).name}...", total=None
                    ),
                )
                for tape in selected_tapes
            ]
            for future in as_completed(futures):
                tape_file, ok, err_msg = future.result()
                if not ok:
                    failures.append((tape_file, err_msg))
                progress.update(overall_task, advance=1)

        summary_desc = (
            f"[bold red]{len(failures)} tape(s) failed verification!"
            if failures
            else "[bold green]All selected tapes rendered and verified!"
        )
        progress.update(overall_task, description=summary_desc)

    return failures


def main() -> None:
    """CLI entrypoint to render and verify VHS demo tapes."""
    bin_dir = str(Path(sys.executable).resolve().parent)
    os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all tapes without prompting",
    )
    parser.add_argument(
        "--tape",
        action="append",
        default=None,
        help="Generate specific tape file(s) by name or path",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Maximum parallel VHS workers (default: 4 for timing stability)",
    )
    args = parser.parse_args()

    all_tapes = sorted(glob.glob("media-gen/tapes/*.tape"))
    if not all_tapes:
        print("No tape files found in media-gen/tapes/")
        sys.exit(0)

    selected_tapes = _select_tapes(
        all_tapes, run_all=args.all, requested=args.tape
    )
    failures = _render_selected_tapes(selected_tapes, args.workers)

    if failures:
        for tape_file, err_msg in failures:
            print(f"FAILED {tape_file}: {err_msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
