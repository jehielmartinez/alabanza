"""Entry point: wire input + app + player + display and run the loop.

    uv run alabanza                       # library from ../tools/downloads
    uv run alabanza --library /path/dir   # explicit library dir
    uv run alabanza --no-video            # audio only (no mpv window)
    uv run alabanza --bt none             # no bluetooth adapter (default: fake)

On the Pi (Phase 1), --gpio adds the real controls and --oled-device the real
panel. Both *add* to the keyboard and terminal rather than replacing them, so
a bench session over SSH shows what the OLED shows and still has `q` to quit.
"""

import argparse
import curses
import sys
from pathlib import Path

from .app import App
from .display import CursesDisplay, ThreadedDisplay
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


def _gpio_input():
    """The real keypad, D-pad and encoder (device only)."""
    from .input_gpio import GpioInput
    return GpioInput()


def _oled_device_display():
    """The real SSD1309 over I2C (device only), rendered off the input loop.

    A frame costs ~54 ms over I2C even at 400 kHz, against ~2 ms for
    everything else in an iteration. Left in the loop it starves the keypad
    scan and presses go missing.
    """
    from .oled import OledDisplay
    return ThreadedDisplay(OledDisplay())


def _power_off() -> None:
    """Power the machine down.

    The app never runs as root, so this needs help. `systemctl poweroff` is
    tried first because it needs no special rule when logind allows it, and
    the narrow sudoers entry installed by provision.sh is the fallback -- that
    entry grants exactly this one command and nothing else.

    A failure here is reported and otherwise ignored: SPEC decision 10 makes
    pulling the plug officially supported, so the worst case is the operator
    doing what they would have done anyway.
    """
    import subprocess

    # sudo first. `systemctl poweroff` has no seat to authenticate against on
    # a headless box, so logind asks polkit, which prompts for a password on
    # the console -- and the console is a projector. --no-ask-password makes
    # the fallback fail quietly instead of asking.
    for command in (["sudo", "-n", "/sbin/poweroff"],
                    ["systemctl", "--no-ask-password", "poweroff"]):
        try:
            subprocess.run(command, check=True, timeout=15,
                           capture_output=True)
            return
        except (OSError, subprocess.SubprocessError):
            continue
    print("could not power off — check the sudoers rule from provision.sh",
          file=sys.stderr)


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
        settings_path: Path, oled: bool, bt_choice: str, gpio: bool,
        oled_device: bool) -> bool:
    """Returns True if the operator asked for the device to power off."""
    screen.timeout(TICK_MS)
    screen.keypad(True)
    displays = [CursesDisplay(screen)]
    if oled:
        displays.append(_oled_emulator_display())
    if oled_device:
        displays.append(_oled_device_display())
    controls = _gpio_input() if gpio else None
    player = Player(video=video)
    bt = _bluetooth_backend(bt_choice)
    app = App(library_dir, player, settings_path, bt)
    if app.library.warnings:
        app.flash(f"{len(app.library.warnings)} library warnings", 4)
    try:
        while not app.quit_requested:
            # getch blocks up to TICK_MS and is what paces the loop, so it
            # stays in the path even when the real controls are wired.
            event = read_event(screen)
            if event:
                app.handle(event)
            if controls:
                for event in controls.poll():
                    app.handle(event)
                # The keypad scans on its own thread, so a failure there can
                # only reach the operator through the panel.
                fault = controls.take_fault()
                if fault:
                    app.flash(fault, 6)
            vm = app.tick()
            for display in displays:
                display.render(vm)
        return app.shutdown_requested
    finally:
        if controls:
            controls.close()
        for display in displays:
            if hasattr(display, "close"):
                display.close()
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
    parser.add_argument("--gpio", action="store_true",
                        help="also read the real keypad, D-pad and encoder "
                             "(device only; keyboard stays live)")
    parser.add_argument("--oled-device", action="store_true",
                        help="also draw on the real SSD1309 over I2C "
                             "(device only)")
    args = parser.parse_args()
    shutdown = curses.wrapper(run, args.library, not args.no_video,
                              args.settings, args.oled, args.bt, args.gpio,
                              args.oled_device)
    # After curses has restored the terminal, so a failure is readable.
    if shutdown:
        _power_off()
    return 0


if __name__ == "__main__":
    sys.exit(main())
