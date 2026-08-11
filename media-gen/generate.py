#!/usr/bin/env python3
"""Script to run VHS tapes and generate GIFs interactively or all at once."""

import argparse
import glob
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import questionary
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


def run_vhs(tape_file, progress, task_id):
    """Execute vhs for a tape file and capture output."""
    subprocess.run(["vhs", tape_file], capture_output=True, text=True)
    # Hide the task when it's done so it disappears from the list
    progress.update(task_id, visible=False)
    return tape_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all tapes without prompting",
    )
    args = parser.parse_args()

    all_tapes = sorted(glob.glob("media-gen/tapes/*.tape"))

    if not all_tapes:
        print("No tape files found in media-gen/tapes/")
        sys.exit(0)

    if args.all:
        selected_tapes = all_tapes
    else:
        choices = [
            questionary.Choice(title=Path(t).name, value=t) for t in all_tapes
        ]
        selected_tapes = questionary.checkbox(
            "Select which tapes to generate "
            "(Space to toggle, Enter to confirm):",
            choices=choices,
        ).ask()

        if not selected_tapes:
            print("No tapes selected. Exiting.")
            sys.exit(0)

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

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for tape in selected_tapes:
                task_id = progress.add_task(
                    f"[yellow]Rendering {Path(tape).name}...", total=None
                )
                futures.append(
                    executor.submit(run_vhs, tape, progress, task_id)
                )

            for future in as_completed(futures):
                future.result()
                progress.update(overall_task, advance=1)

        progress.update(
            overall_task,
            description="[bold green]All selected tapes rendered!",
        )
