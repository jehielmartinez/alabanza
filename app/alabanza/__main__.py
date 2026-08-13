"""Entry point: wire input + app + player + display and run the loop.

    uv run alabanza                       # library from ../tools/downloads
    uv run alabanza --library /path/dir   # explicit library dir
    uv run alabanza --no-video            # audio only (no mpv window)
    uv run alabanza --bt none             # no bluetooth adapter (default: fake)
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


def _oled_emulator_display():
    """The real OLED renderer drawn into a pygame window (dev only)."""
    import pygame
    from luma.emulator.device import pygame as pygame_device

    from .oled import OledDisplay

    class EmulatorDisplay(OledDisplay):
        def render(self, vm) -> None:
            # macOS marks the window unresponsive unless its event queue
            # is drained every frame (worst once mpv's window takes focus)
            pygame.event.pump()
            super().render(vm)

    return EmulatorDisplay(
        pygame_device(width=128, height=64, scale=4, transform="identity"))


def _bluetooth_backend(choice: str):
    from .bluetooth import NullBackend

    if choice == "fake":
        from .bt_fake import FakeBackend
        return FakeBackend()
    if choice == "real":
        try:
            from .bt_bluez import BluezBackend
            return BluezBackend()
        except ImportError:
            # missing dbus-fast must not stop the device from playing hymns
            # into the jack; the OLED will simply report Bluetooth as off
            return NullBackend()
    return NullBackend()


def run(screen: "curses.window", library_dir: Path, video: bool,
        settings_path: Path, oled: bool, bt_choice: str) -> None:
    screen.timeout(TICK_MS)
    screen.keypad(True)
    displays = [CursesDisplay(screen)]
    if oled:
        displays.append(_oled_emulator_display())
    player = Player(video=video)
    bt = _bluetooth_backend(bt_choice)
    app = App(library_dir, player, settings_path, bt)
    if app.library.warnings:
        app.flash(f"{len(app.library.warnings)} library warnings", 4)
    try:
        while not app.quit_requested:
            event = read_event(screen)
            if event:
                app.handle(event)
            vm = app.tick()
            for display in displays:
                display.render(vm)
    finally:
        bt.close()
        player.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--no-video", action="store_true",
                        help="audio only; don't open a video window")
    parser.add_argument("--settings", type=Path,
                        default=Path.home() / ".alabanza" / "settings.json",
                        help="settings file (device: on the writable partition)")
    parser.add_argument("--oled", action="store_true",
                        help="also show the exact 128x64 OLED rendering in a "
                             "window (requires: uv sync --extra emu)")
    parser.add_argument("--bt", choices=("fake", "real", "none"), default="fake",
                        help="bluetooth backend: scripted speakers (default), "
                             "real BlueZ (device only), or no adapter")
    args = parser.parse_args()
    curses.wrapper(run, args.library, not args.no_video, args.settings,
                   args.oled, args.bt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
