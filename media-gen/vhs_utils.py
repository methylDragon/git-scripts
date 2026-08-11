"""Utility module for generating banners and typing comments in VHS tapes."""

import argparse
import sys
import termios
import tty

import pyfiglet
from rich.console import Console
from rich.text import Text


def comment_reader():
    """Reads from standard input and prints char-by-char to simulate typing.

    This operates in raw mode to intercept keystrokes in real time.
    Use '@' to toggle a highlight (bold yellow) on and off.
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    hl = False
    try:
        tty.setraw(fd)
        # Enable cursor blinking and set it to a blinking block
        sys.stdout.write("\033[?12h\033[1 q")
        sys.stdout.flush()
        while True:
            c = sys.stdin.read(1)
            match c:
                case "\x03":  # Ctrl+C: Exit the reader loop
                    break
                case "\x0c":  # Ctrl+L: Clear the terminal screen
                    sys.stdout.write("\033[H\033[J")
                case "\r":  # Enter key: Write a carriage return and newline
                    sys.stdout.write("\r\n")
                case "@":  # @ symbol: Toggle highlight formatting on or off
                    hl = not hl
                    sys.stdout.write(
                        chr(27) + "[1;33m" if hl else chr(27) + "[0m"
                    )
                case _:  # Normal character: Echo the character as typed
                    sys.stdout.write(c)
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def banner(text, subtext=None):
    """Renders a large ASCII art banner with a gold-themed gradient.

    Args:
        text (str): The main text to render as ASCII art.
        subtext (str, optional): A subtitle to print beneath the banner.
    """
    if text == "git gh-align-pr-bases-and-sync-stacks":
        text = "align-pr-bases + sync-stacks"

    console = Console()
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
    console.print(rich_text)
    if subtext:
        console.print(f"[italic]{subtext}[/italic]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    reader_parser = subparsers.add_parser("comment_reader")

    banner_parser = subparsers.add_parser("banner")
    banner_parser.add_argument("text")
    banner_parser.add_argument("--subtext", default=None)

    args = parser.parse_args()
    if args.command == "comment_reader":
        comment_reader()
    elif args.command == "banner":
        banner(args.text, args.subtext)
