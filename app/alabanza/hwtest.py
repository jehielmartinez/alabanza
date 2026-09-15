"""Hardware test: press a control, see it named on the panel.

    uv run alabanza-hwtest

This is the tool for bringing up a control PCB. Press every key, rock the
D-pad, spin and push the encoder; each one lights up on the OLED and prints
a line naming the BCM pins it came in on. A coverage map along the bottom
shows what has not been pressed yet, so a board is signed off by sweeping it
until the map is full rather than by remembering what you already tried.

It tests the panel as much as the controls: everything it reports, it reports
*on the OLED*, so a working display is a precondition for a green run. The
startup frame draws a border at the glass edge and a line of accented
Spanish, which is where a mis-set panel size or a missing font shows up.

Why a separate entry point and not `pytest -m device`: those answer "is this
pin claimable", which is a question about wiring that a machine can settle
alone. This answers "does the key marked 7 report a 7", which needs a finger
and an eye, and is the one that catches a swapped row, a mirrored connector
or a mislabelled switch — HARDWARE.md's pre-fab list warns about all three.
"""

import argparse
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .events import Event, Kind
from .oled import FONT_SMALL, HEIGHT, SEP_Y, WIDTH, _fit
from .pins import (
    DPAD_CENTRE,
    DPAD_DOWN,
    DPAD_LEFT,
    DPAD_RIGHT,
    DPAD_UP,
    ENCODER_A,
    ENCODER_B,
    ENCODER_PUSH,
    KEYPAD_COLS,
    KEYPAD_ROWS,
)

_FONTS = Path(__file__).parent / "fonts"
# 20, not larger: the band between the separator and the coverage map is 24 px,
# and "Izquierda" has a descender that has to land inside it.
FONT_BIG = ImageFont.truetype(str(_FONTS / "TerminusTTF-Bold-4.49.3.ttf"), 20,
                              layout_engine=ImageFont.Layout.BASIC)

# The 3x4 legend as characters. input_gpio.KEYPAD holds the same layout as
# Events; this is the second copy, and tests/test_input_gpio.py fails if the
# two stop agreeing — the same bargain BUILD-PLAN.md's pin map makes, and for
# the same reason: the alternative is importing gpiozero to draw a screen.
KEYPAD_LAYOUT = ("123", "456", "789", "*0#")

# Every control this board has, in the order the coverage map shows them.
# `glyph` is one character because a cell is 10 px and the font is 6 px wide;
# the full name only has to fit the big row, which is the whole panel.


@dataclass(frozen=True)
class Control:
    id: str
    glyph: str
    name: str
    pins: tuple[int, ...]


def _keypad_controls() -> list[Control]:
    out = []
    for r, row in enumerate(KEYPAD_LAYOUT):
        for c, char in enumerate(row):
            out.append(Control(f"k{char}", char, f"Tecla {char}",
                               (KEYPAD_ROWS[r], KEYPAD_COLS[c])))
    return out


CONTROLS: tuple[Control, ...] = (
    *_keypad_controls(),
    Control("up",      "^", "Arriba",       (DPAD_UP,)),
    Control("down",    "v", "Abajo",        (DPAD_DOWN,)),
    Control("left",    "<", "Izquierda",    (DPAD_LEFT,)),
    Control("right",   ">", "Derecha",      (DPAD_RIGHT,)),
    Control("centre",  "O", "Centro",       (DPAD_CENTRE,)),
    Control("cw",      "+", "Rueda +",      (ENCODER_A, ENCODER_B)),
    Control("ccw",     "-", "Rueda -",      (ENCODER_A, ENCODER_B)),
    Control("push",    "P", "Pulsar rueda", (ENCODER_PUSH,)),
    Control("held",    "H", "Rueda held",   (ENCODER_PUSH,)),
)
BY_ID = {control.id: control for control in CONTROLS}

# Events that prove nothing on their own: a release only happens after a push
# that already counted, so requiring it would just make the map harder to
# fill without testing another solder joint. A held * is the same -- the
# press that started it already proved k*, and it is the same contact.
_IGNORED = {Kind.PUSH_RELEASE, Kind.STAR_HELD}

_FROM_KIND = {
    Kind.STAR: "k*", Kind.CONFIRM: "k#", Kind.UP: "up", Kind.DOWN: "down",
    Kind.SEEK_BACK: "left", Kind.SEEK_FWD: "right", Kind.PLAY_PAUSE: "centre",
    Kind.WHEEL_CW: "cw", Kind.WHEEL_CCW: "ccw", Kind.PUSH: "push",
    Kind.PUSH_HELD: "held",
}


def control_for(event: Event) -> Control | None:
    """The control an event came from, or None if it proves nothing."""
    if event.kind in _IGNORED:
        return None
    key = f"k{event.value}" if event.kind is Kind.DIGIT else _FROM_KIND.get(event.kind)
    return BY_ID.get(key or "")


@dataclass
class State:
    seen: set[str] = field(default_factory=set)
    last: Control | None = None
    note: str = ""

    @property
    def remaining(self) -> list[Control]:
        return [c for c in CONTROLS if c.id not in self.seen]

    def record(self, control: Control) -> None:
        self.seen.add(control.id)
        self.last = control
        self.note = ""


# --- the panel ------------------------------------------------------------
#
# Pure Pillow and no luma, like oled.py, so the screens can be rendered and
# eyeballed on a laptop before any of it meets a board.

# FONT_SMALL is 12 px tall, so a shorter cell clips the glyph into the row
# below it. Two rows of 12 anchored to the bottom edge is the whole budget.
CELL_W, CELL_H = 10, 12
MAP_TOP = HEIGHT - 2 * CELL_H


def _cells(draw: ImageDraw.ImageDraw, seen: set[str]) -> None:
    """The coverage map: every control, filled once it has been pressed."""
    rows = (CONTROLS[:12], CONTROLS[12:])        # keypad, then everything else
    for r, row in enumerate(rows):
        y = MAP_TOP + r * CELL_H
        for c, control in enumerate(row):
            x = c * CELL_W
            box = (x, y, x + CELL_W - 2, y + CELL_H - 1)
            hit = control.id in seen
            draw.rectangle(box, outline=1, fill=1 if hit else 0)
            draw.text((x + 2, y), control.glyph, font=FONT_SMALL,
                      fill=0 if hit else 1)


def screen(state: State) -> Image.Image:
    """One frame: what was pressed, in large, over the coverage map."""
    image = Image.new("1", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)

    done, total = len(state.seen), len(CONTROLS)
    # The status row is contextual: the board's name until the first press,
    # then the pins the last press arrived on — which is the number you are
    # actually looking for when a key reports the wrong thing.
    left = " ".join(f"BCM{p}" for p in state.last.pins) if state.last \
        else "PRUEBA PANEL"
    right = "COMPLETO" if done == total else f"{done}/{total}"
    draw.text((0, 0), _fit(draw, left, FONT_SMALL, WIDTH - 56),
              font=FONT_SMALL, fill=1)
    draw.text((WIDTH - int(draw.textlength(right, font=FONT_SMALL)), 0),
              right, font=FONT_SMALL, fill=1)
    draw.line((0, SEP_Y, WIDTH, SEP_Y), fill=1)

    if state.note:
        draw.text((0, SEP_Y + 7), _fit(draw, state.note, FONT_SMALL),
                  font=FONT_SMALL, fill=1)
    elif state.last is None:
        draw.text((0, SEP_Y + 7), "Pulsa un control", font=FONT_SMALL, fill=1)
    else:
        # Centred and large — readable at arm's length, which is how it gets
        # used: eyes on the board, glance up, press the next one.
        name = _fit(draw, state.last.name, FONT_BIG)
        draw.text(((WIDTH - int(draw.textlength(name, font=FONT_BIG))) // 2,
                   SEP_Y + 3), name, font=FONT_BIG, fill=1)

    _cells(draw, state.seen)
    return image


def splash() -> Image.Image:
    """The startup frame, which is a test of the glass rather than the keys.

    A one-pixel border on the outermost row and column proves the panel is
    addressed edge to edge: get HEIGHT or the SSD1309's start-line wrong and
    the bottom rule is missing or wrapped. The accented line proves the font
    is the vendored Terminus and not a fallback with no Spanish in it.
    """
    image = Image.new("1", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=1)
    draw.text((6, 8), f"OLED {WIDTH}x{HEIGHT}", font=FONT_SMALL, fill=1)
    draw.text((6, 22), "ÁÉÍÓÚ ÑÜ ¿¡", font=FONT_SMALL, fill=1)
    draw.text((6, 36), "Prueba de panel", font=FONT_SMALL, fill=1)
    for x in range(0, WIDTH, 4):                # a comb along the last row
        draw.point((x, HEIGHT - 3), fill=1)
    return image


# --- the tool -------------------------------------------------------------


class PanelWriter:
    """Pushes frames at the panel, survives a bad one, and keeps score.

    A 2.42" module on bench wiring NACKs now and then at the 400 kHz
    provision.sh sets, and an unguarded write turns that into a traceback
    that takes the *button* test down with it — which is how this tool first
    died at key 8 with thirteen controls still untested. display.py's
    ThreadedDisplay already applies this policy for the app ("a panel that
    fails must not stop the hymns"); a bring-up tool has even less business
    quitting.

    The score is not bookkeeping: on a board being brought up, "4000 frames,
    3 failed writes" is a measurement of the I2C bus, and the difference
    between a panel worth soldering down and one worth re-checking.
    """

    def __init__(self, device):
        self.device = device
        self.frames = 0
        self.errors = 0
        self.last_error = ""
        self._last: bytes | None = None

    def write(self, image) -> bool:
        """Draw, if it would change anything. True if the panel took it."""
        frame = image.convert(self.device.mode)
        data = frame.tobytes()
        if data == self._last:
            return True
        try:
            self.device.display(frame)
        except Exception as exc:                # noqa: BLE001 - see docstring
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False                        # _last unchanged: retry it
        self._last = data
        self.frames += 1
        return True


def _open_panel(enabled: bool):
    """The OLED, or None if it is not there yet.

    A board is wired one peripheral at a time (BUILD-PLAN.md Phase 1), so a
    missing panel must not block testing the keys — it degrades to the
    terminal and says so, rather than refusing to start.
    """
    if not enabled:
        return None
    try:
        from .oled import OledDisplay
        return OledDisplay()
    except Exception as exc:                    # noqa: BLE001
        print(f"!! no OLED ({exc}); controls only", file=sys.stderr)
        return None


def _interrupt(signum, frame):
    """Make a kill behave like Ctrl+C, so the summary still gets printed.

    The useful non-interactive form is `timeout 60 alabanza-hwtest`, and a
    run that reports nothing because it was stopped the way it was always
    going to be stopped is not much of a test.
    """
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-oled", action="store_true",
                        help="skip the panel; report to the terminal only")
    parser.add_argument("--seconds", type=float, default=None,
                        help="stop and report after this long (default: "
                             "run until Ctrl+C)")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _interrupt)

    panel = _open_panel(not args.no_oled)
    writer = PanelWriter(panel.device) if panel is not None else None
    if writer is not None:
        writer.write(splash())
        time.sleep(2.0)

    from .input_gpio import GpioInput          # imports gpiozero; device only
    controls = GpioInput()

    state = State()
    print(f"Press every control. {len(CONTROLS)} to go; Ctrl+C to stop.\n"
          f"  keypad {' '.join(KEYPAD_LAYOUT)}   D-pad ^ v < > O"
          f"   wheel + -   push P   hold H\n", flush=True)
    started = time.monotonic()
    try:
        while args.seconds is None or time.monotonic() - started < args.seconds:
            for event in controls.poll():
                control = control_for(event)
                if control is None:
                    continue
                first = control.id not in state.seen
                state.record(control)
                print(f"  {time.monotonic() - started:6.1f}s  "
                      f"{control.name:<14} {'':2}"
                      f"{' '.join(f'BCM{p}' for p in control.pins):<12}"
                      f"{'' if not first else f'  [{len(state.seen)}/{len(CONTROLS)}]'}",
                      flush=True)
            fault = controls.take_fault()
            if fault:
                state.note = fault
                print(f"  !! {fault}: {controls._last_error}", flush=True)
            if writer is not None and not writer.write(screen(state)):
                if writer.errors == 1:          # say it once, then just count
                    print(f"  !! panel write failed: {writer.last_error}",
                          flush=True)
            time.sleep(0.02)
    except KeyboardInterrupt:
        print()
    finally:
        controls.close()
        if panel is not None:
            panel.close()

    missing = state.remaining
    if missing:
        print(f"{len(missing)} control(s) never responded:")
        for control in missing:
            print(f"  {control.name:<14} "
                  f"{' '.join(f'BCM{p}' for p in control.pins)}")
    if writer is not None:
        print(f"Panel: {writer.frames} frames written, "
              f"{writer.errors} failed.")
        if writer.errors:
            print(f"  last: {writer.last_error}")
            print("  A panel that drops writes is a bus problem, not a code "
                  "one: check SDA/SCL length and pull-ups, or drop "
                  "dtparam=i2c_arm_baudrate in /boot/firmware/config.txt.")
    if missing or (writer is not None and writer.errors):
        return 1
    print(f"All {len(CONTROLS)} controls responded and the panel took every "
          f"frame.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
