"""Utility module for generating banners and typing comments in VHS tapes."""

import argparse
import signal
import sys
import termios
import tty
from pathlib import Path

import pyfiglet
from rich.console import Console
from rich.text import Text


def banner(text: str, subtext: str | None = None) -> None:
    """Renders a large ASCII art banner with a gold-themed gradient.

    Args:
        text: The main text to render as ASCII art.
        subtext: A subtitle to print beneath the banner.
    """
    if text == "git gh-align-pr-bases-and-sync-stacks":
        text = "align-pr-bases + sync-stacks"

    console = Console(width=120, force_terminal=True)
    art = pyfiglet.figlet_format(text, font="smblock", width=120)
    colors = ["dark_goldenrod", "goldenrod", "gold3", "gold1", "yellow3"]
    rich_text = Text()
    for i, line in enumerate(art.splitlines()):
        if not line.strip():
            continue
        for j, char in enumerate(line):
            rich_text.append(char, style=colors[(i + j // 4) % len(colors)])
        rich_text.append("\n")
    rich_text.rstrip()
    if subtext:
        console.print(rich_text)
        console.print(f"[italic]{subtext}[/italic]", end="")
    else:
        console.print(rich_text, end="")
    sys.stdout.flush()


def comment_reader(
    ready_file: str | None = None,
    banner_text: str | None = None,
    banner_subtext: str | None = None,
) -> None:
    """Reads from standard input and prints char-by-char to simulate typing.

    This operates in raw mode to intercept keystrokes in real time.
    Use '@' to toggle a highlight (bold yellow) on and off.
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    is_highlighted = False
    first_input_received = False

    def _redraw_on_resize(_signum: int, _frame: object) -> None:
        if not first_input_received and banner_text:
            sys.stdout.write("\033[H\033[J")
            banner(banner_text, banner_subtext)
            sys.stdout.write("\033[?12h\033[1 q")
            sys.stdout.flush()

    prev_winch = signal.signal(signal.SIGWINCH, _redraw_on_resize)
    try:
        tty.setraw(fd)
        raw_mode = termios.tcgetattr(fd)
        raw_mode[1] |= termios.OPOST
        termios.tcsetattr(fd, termios.TCSANOW, raw_mode)
        # Enable cursor blinking and set it to a blinking block
        sys.stdout.write("\033[?12h\033[1 q")
        sys.stdout.flush()
        if ready_file:
            Path(ready_file).write_text("ready\n", encoding="utf-8")
        while True:
            c = sys.stdin.read(1)
            first_input_received = True
            match c:
                case "" | "\x03":  # EOF or Ctrl+C: Exit the reader loop
                    break
                case "\x0c":  # Ctrl+L: Clear the terminal screen
                    sys.stdout.write("\033[H\033[J")
                case "\r":  # Enter key: Write a carriage return and newline
                    sys.stdout.write("\r\n")
                case "@":  # @ symbol: Toggle highlight formatting on or off
                    is_highlighted = not is_highlighted
                    sys.stdout.write(
                        chr(27) + "[1;33m"
                        if is_highlighted
                        else chr(27) + "[0m"
                    )
                case _:  # Normal character: Echo the character as typed
                    sys.stdout.write(c)
            sys.stdout.flush()
    finally:
        signal.signal(signal.SIGWINCH, prev_winch)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main() -> None:
    """CLI entrypoint for VHS banner and comment reader utilities."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    reader_parser = subparsers.add_parser("comment_reader")
    reader_parser.add_argument("--ready-file", default=None)

    banner_parser = subparsers.add_parser("banner")
    banner_parser.add_argument("text")
    banner_parser.add_argument("--subtext", default=None)
    banner_parser.add_argument(
        "--comment-reader",
        action="store_true",
        help="Immediately enter raw comment_reader mode after rendering.",
    )
    banner_parser.add_argument("--ready-file", default=None)

    args = parser.parse_args()
    if args.command == "comment_reader":
        comment_reader(ready_file=args.ready_file)
    elif args.command == "banner":
        sys.stdout.write("\033[H\033[J")
        sys.stdout.flush()
        banner(args.text, args.subtext)
        if args.comment_reader:
            comment_reader(
                ready_file=args.ready_file,
                banner_text=args.text,
                banner_subtext=args.subtext,
            )


if __name__ == "__main__":
    main()
