"""Entry point: wire input + app + player + display and run the loop.

    uv run alabanza                       # library from ../tools/downloads
    uv run alabanza --library /path/dir   # explicit library dir
    uv run alabanza --no-video            # audio only (no mpv window)
"""

import argparse
import curses
import sys
from pathlib import Path

from .app import App
from .display import CursesDisplay
from .input_keyboard import read_event
from .player import Player

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
# provisioned library first; raw downloads as dev fallback
DEFAULT_LIBRARY = _TOOLS / "library" if (_TOOLS / "library" / "manifest.json").exists() else _TOOLS / "downloads"
TICK_MS = 50


def run(screen: "curses.window", library_dir: Path, video: bool) -> None:
    screen.timeout(TICK_MS)
    screen.keypad(True)
    display = CursesDisplay(screen)
    player = Player(video=video)
    app = App(library_dir, player)
    if app.library.warnings:
        app.flash(f"{len(app.library.warnings)} library warnings", 4)
    try:
        while not app.quit_requested:
            event = read_event(screen)
            if event:
                app.handle(event)
            display.render(app.tick())
    finally:
        player.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--no-video", action="store_true",
                        help="audio only; don't open a video window")
    args = parser.parse_args()
    curses.wrapper(run, args.library, not args.no_video)
    return 0


if __name__ == "__main__":
    sys.exit(main())
