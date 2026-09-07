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

import threading
import time
from collections import deque

from gpiozero import Button, DigitalInputDevice, OutputDevice, RotaryEncoder

from .events import Event, Kind
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

# The 3x4 legend, in scan order. Row 3 is `* 0 #` — matches the Value fields
# HARDWARE.md layout rule 2 requires on the switches, so a key that reports
# the wrong digit is a placement fault, not a firmware one.
KEYPAD = (
    (Event(Kind.DIGIT, 1), Event(Kind.DIGIT, 2), Event(Kind.DIGIT, 3)),
    (Event(Kind.DIGIT, 4), Event(Kind.DIGIT, 5), Event(Kind.DIGIT, 6)),
    (Event(Kind.DIGIT, 7), Event(Kind.DIGIT, 8), Event(Kind.DIGIT, 9)),
    (Event(Kind.STAR),     Event(Kind.DIGIT, 0), Event(Kind.CONFIRM)),
)

BOUNCE = 0.02        # software debounce, both for gpiozero and the matrix
SEEK_REPEAT = 0.4    # held ◀/▶ repeats at this interval (SPEC: "held = repeat")
_SETTLE = 50e-6      # let a driven row settle before reading the columns
SCAN_HZ = 50         # keypad samples per second, on its own thread
HELD_REPEAT = 0.25   # how often a held encoder push re-announces itself


class _Matrix:
    """The 3x4 keypad, scanned one row at a time.

    HARDWARE.md §1 requires driving one row low with the others **Hi-Z**,
    never all four as outputs: two driven rows bridged by a keypress is a
    fault current through the GPIO pads. The 12 diodes make that impossible
    anyway, but they are insurance against this code, not a licence for it —
    so the idle rows are genuinely released to inputs between reads.

    Debounce is explicit. It used to come free: scanning once per 50 ms tick
    meant bounce had always settled before the next sample. Scanning on its
    own thread at 50 Hz is twice as fast, and close enough to contact bounce
    that a press could be counted twice, so each key now ignores a second
    edge within BOUNCE of its last one.
    """

    def __init__(self, rows=KEYPAD_ROWS, cols=KEYPAD_COLS):
        self._rows = [OutputDevice(pin, initial_value=False) for pin in rows]
        for row in self._rows:
            self._release(row)
        # pull_up=True inverts, so .value is 1 exactly when the column is
        # pulled low — i.e. when a key on the driven row is down.
        self._cols = [DigitalInputDevice(pin, pull_up=True) for pin in cols]
        self._down: set[tuple[int, int]] = set()
        self._changed: dict[tuple[int, int], float] = {}

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
        now = time.monotonic()
        events = []
        for key in sorted(down ^ self._down):          # anything that moved
            if now - self._changed.get(key, -1.0) < BOUNCE:
                continue
            self._changed[key] = now
            if key in down:                            # a press, not a release
                events.append(KEYPAD[key[0]][key[1]])
        self._down = down
        return events

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
        self._button(ENCODER_PUSH, Kind.PUSH, release=Kind.PUSH_RELEASE,
                     held=Kind.PUSH_HELD)
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

        # The matrix is scanned on its own thread. Everything else already
        # arrives by interrupt -- gpiozero's callbacks for the buttons and the
        # encoder -- so the keypad was the one control whose responsiveness
        # depended on how busy the app loop happened to be. With a 96 ms OLED
        # write in that loop it sampled ~6 times a second and dropped presses.
        self._stop = threading.Event()
        self._scanner = threading.Thread(target=self._scan_loop, daemon=True,
                                         name="alabanza-keypad")
        self._scanner.start()

    def _scan_loop(self) -> None:
        period = 1.0 / SCAN_HZ
        while not self._stop.is_set():
            for event in self._matrix.scan():
                self._queue.append(event)
            self._stop.wait(period)

    def _emit(self, kind: Kind):
        def push():
            self._queue.append(Event(kind))
        return push

    def _button(self, pin: int, kind: Kind, repeat: bool = False,
                release: Kind | None = None, held: Kind | None = None) -> None:
        # `held` reports *that* the key is still down, repeatedly; the app
        # decides what a long hold means, because it owns the injected clock
        # and timing here would put the logic on the one thread the test
        # suite cannot drive. It is a keepalive rather than a cancel signal
        # on purpose: a backend that cannot report holding simply stops
        # sending, and the app gives up on its own. Waiting for a release
        # that never comes would leave the keyboard backend one keypress and
        # three seconds away from powering off the device.
        button = Button(pin, pull_up=True, bounce_time=BOUNCE,
                        hold_time=HELD_REPEAT if held else SEEK_REPEAT,
                        hold_repeat=bool(repeat or held))
        button.when_pressed = self._emit(kind)
        if repeat:
            button.when_held = self._emit(kind)
        elif held is not None:
            button.when_held = self._emit(held)
        if release is not None:
            button.when_released = self._emit(release)
        self._buttons.append(button)

    def poll(self) -> list[Event]:
        """Non-blocking, and now genuinely cheap: everything arrives on other
        threads, so this only drains what they queued."""
        events = []
        while self._queue:
            events.append(self._queue.popleft())
        return events

    def close(self) -> None:
        self._stop.set()
        self._scanner.join(timeout=1.0)
        self._matrix.close()
        self._encoder.close()
        for button in self._buttons:
            button.close()
