"""GPIO input backend (Phase 1): the real controls -> Events.

The device twin of input_keyboard.py. Same job, same vocabulary: turn what
the operator physically did into the Events in events.py, and hand them to
the app loop one tick at a time.

Pin assignments are BCM and come from the pin map in docs/BUILD-PLAN.md,
which is the source of truth. Nothing here may invent a pin.

Three kinds of control, three mechanisms:

  keypad    scanned matrix, polled once per poll() call (see _Matrix)
  D-pad     one gpiozero Button per key, callback-driven
  encoder   gpiozero RotaryEncoder + a Button for the push

Callbacks fire on gpiozero's own threads, so everything lands in a deque
(append/popleft are atomic under the GIL) and poll() drains it from the app
thread. poll() returns a *list*, not a single event: a knob spun hard emits
detents faster than the 50 ms tick, and returning one per tick would make
the volume lag behind the hand and keep climbing after it stopped.

RESCAN and QUIT are deliberately absent — they are dev conveniences with no
key on the panel.
"""

import time
from collections import deque

from gpiozero import Button, DigitalInputDevice, OutputDevice, RotaryEncoder

from .events import Event, Kind

# --- pin map (BCM) — docs/BUILD-PLAN.md ------------------------------------
KEYPAD_ROWS = (5, 6, 13, 19)
KEYPAD_COLS = (12, 16, 20)
ENCODER_A, ENCODER_B, ENCODER_PUSH = 17, 27, 22
DPAD_CENTRE = 23
DPAD_LEFT, DPAD_RIGHT = 25, 26
DPAD_UP, DPAD_DOWN = 7, 8

# The 3x4 legend, in scan order. Row 3 is `* 0 #` — matches the Value fields
# HARDWARE.md layout rule 2 requires on the switches, so a key that reports
# the wrong digit is a placement fault, not a firmware one.
KEYPAD = (
    (Event(Kind.DIGIT, 1), Event(Kind.DIGIT, 2), Event(Kind.DIGIT, 3)),
    (Event(Kind.DIGIT, 4), Event(Kind.DIGIT, 5), Event(Kind.DIGIT, 6)),
    (Event(Kind.DIGIT, 7), Event(Kind.DIGIT, 8), Event(Kind.DIGIT, 9)),
    (Event(Kind.STAR),     Event(Kind.DIGIT, 0), Event(Kind.CONFIRM)),
)

BOUNCE = 0.02        # gpiozero software debounce on the direct buttons
SEEK_REPEAT = 0.4    # held ◀/▶ repeats at this interval (SPEC: "held = repeat")
_SETTLE = 50e-6      # let a driven row settle before reading the columns


class _Matrix:
    """The 3x4 keypad, scanned one row at a time.

    HARDWARE.md §1 requires driving one row low with the others **Hi-Z**,
    never all four as outputs: two driven rows bridged by a keypress is a
    fault current through the GPIO pads. The 12 diodes make that impossible
    anyway, but they are insurance against this code, not a licence for it —
    so the idle rows are genuinely released to inputs between reads.

    Debounce is free here. poll() runs once per 50 ms tick and a press is
    emitted on the not-pressed -> pressed edge between two scans, so contact
    bounce (~1-5 ms) has always settled by the time the next sample lands.
    """

    def __init__(self, rows=KEYPAD_ROWS, cols=KEYPAD_COLS):
        self._rows = [OutputDevice(pin, initial_value=False) for pin in rows]
        for row in self._rows:
            self._release(row)
        # pull_up=True inverts, so .value is 1 exactly when the column is
        # pulled low — i.e. when a key on the driven row is down.
        self._cols = [DigitalInputDevice(pin, pull_up=True) for pin in cols]
        self._down: set[tuple[int, int]] = set()

    @staticmethod
    def _release(row: OutputDevice) -> None:
        """Put a row back to a true Hi-Z: input *and* no pull.

        The pull matters. A BCM pin reverts to its power-on pull when it
        becomes an input, and that is pull-*down* for GPIO 9-27 — which
        covers rows 13 and 19. An idle row weakly pulled down sits across a
        pressed key's diode against the column's ~50k pull-up, parking the
        column near 1.6 V: undefined, and read as a phantom press about as
        often as not. Rows 5 and 6 happen to default to pull-up and would
        have looked fine, which is exactly how this hides.
        """
        row.pin.function = "input"
        row.pin.pull = "floating"

    def scan(self) -> list[Event]:
        """One full pass. Returns the events for keys pressed since the last."""
        down = set()
        for r, row in enumerate(self._rows):
            row.pin.function = "output"
            row.off()
            time.sleep(_SETTLE)
            for c, col in enumerate(self._cols):
                if col.value:
                    down.add((r, c))
            self._release(row)
        new = down - self._down
        self._down = down
        return [KEYPAD[r][c] for r, c in sorted(new)]

    def close(self) -> None:
        for device in (*self._rows, *self._cols):
            device.close()


class GpioInput:
    """Every physical control, as one pollable source of Events."""

    def __init__(self):
        self._queue: deque[Event] = deque()
        self._matrix = _Matrix()
        self._buttons: list[Button] = []

        # The D-pad and the encoder push: one GPIO each, internal pull-up,
        # switch to ground (HARDWARE.md §2, §4).
        self._button(DPAD_CENTRE, Kind.PLAY_PAUSE)
        self._button(DPAD_UP, Kind.UP)
        self._button(DPAD_DOWN, Kind.DOWN)
        self._button(ENCODER_PUSH, Kind.PUSH)
        # Seek is the one control the spec asks to repeat while held.
        self._button(DPAD_LEFT, Kind.SEEK_BACK, repeat=True)
        self._button(DPAD_RIGHT, Kind.SEEK_FWD, repeat=True)

        # max_steps=0 leaves the count unbounded: the wheel is a relative
        # control (volume, list cursor) and must never saturate at an end.
        # No bounce_time — the RC filter on A/B (HARDWARE.md §3) is the
        # debounce, and doing it twice eats detents on a fast spin.
        self._encoder = RotaryEncoder(ENCODER_A, ENCODER_B, max_steps=0)
        self._encoder.when_rotated_clockwise = self._emit(Kind.WHEEL_CW)
        self._encoder.when_rotated_counter_clockwise = self._emit(Kind.WHEEL_CCW)

    def _emit(self, kind: Kind):
        def push():
            self._queue.append(Event(kind))
        return push

    def _button(self, pin: int, kind: Kind, repeat: bool = False) -> None:
        button = Button(pin, pull_up=True, bounce_time=BOUNCE,
                        hold_time=SEEK_REPEAT, hold_repeat=repeat)
        button.when_pressed = self._emit(kind)
        if repeat:
            button.when_held = self._emit(kind)
        self._buttons.append(button)

    def poll(self) -> list[Event]:
        """Non-blocking: the keypad scan plus whatever the callbacks queued."""
        events = self._matrix.scan()
        while self._queue:
            events.append(self._queue.popleft())
        return events

    def close(self) -> None:
        self._matrix.close()
        self._encoder.close()
        for button in self._buttons:
            button.close()
