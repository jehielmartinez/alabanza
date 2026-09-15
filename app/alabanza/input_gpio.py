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

import logging
import threading
import time
from collections import deque

from gpiozero import Button, DigitalInputDevice, OutputDevice, RotaryEncoder

from .events import Event, Kind
from .input_evdev import EvdevControls
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

# The one keypad key with something to say while it is held: * on the slide
# screen goes back to the picker. Same contract as the encoder push -- a
# keepalive every HELD_REPEAT, the app times the hold and gives up when they
# stop -- so a release this scan never sees is still safe.
KEYPAD_HELD = {(3, 0): Kind.STAR_HELD}
HELD_REPEAT = 0.25

# The panel can only fit "the keypad stopped"; *why* it stopped goes here, so
# a unit in the field leaves a trace in the journal rather than a mystery.
log = logging.getLogger(__name__)

BOUNCE = 0.02        # software debounce, both for gpiozero and the matrix
SEEK_REPEAT = 0.4    # held ◀/▶ repeats at this interval (SPEC: "held = repeat")
                     # (input_evdev.py carries the same two numbers for the
                     # kernel path; change both or the two backends drift)
_SETTLE = 50e-6      # let a driven row settle before reading the columns
# Keypad samples per second, on its own thread. 50 Hz once; 30 Hz since the
# Zero W, where each wake-up of the thread is Python and scheduler overhead
# on the only core. 33 ms is still far below any human press, and BOUNCE is
# unaffected: it measures time between changes, not passes.
SCAN_HZ = 30
HELD_REPEAT = 0.25   # how often a held encoder push re-announces itself
FAULT_AFTER = 25     # consecutive failed scans (~0.5 s) before the panel hears
FAULT_PERIOD = 0.5   # retry interval once the keypad is given up for lost

# What the panel says when the keypad stops answering, and when it comes back.
# Spanish like every other operator-facing string, and inside the 21 characters
# app.MSG_CHARS fits across 128 px.
MSG_KEYPAD_LOST = "Teclado sin respuesta"
MSG_KEYPAD_BACK = "Teclado restablecido"


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
        self._held_due: dict[tuple[int, int], float] = {}
        # The scan talks to lgpio directly when it can. Through gpiozero a
        # row costs a dozen Python-level calls -- function, state, pull, and
        # a mode query behind every column read -- which profiled as the
        # single largest consumer of the Zero W's core at idle. Six C calls
        # do the same job. gpiozero still owns the pins (claiming, closing,
        # the fault diagnostics in modes()); this only borrows its handle.
        self._lg = self._h = None
        factory = self._rows[0].pin.factory
        if hasattr(factory, "_handle"):
            try:
                import lgpio
            except ImportError:
                lgpio = None
            if lgpio is not None:
                self._lg, self._h = lgpio, factory._handle
                self._row_nums = [row.pin._number for row in self._rows]
                self._col_nums = [col.pin._number for col in self._cols]
                # Rows become open-drain outputs, claimed once. The BCM2835
                # has no open-drain hardware; the kernel emulates it, and
                # its emulation is exactly _release(): writing 1 turns the
                # line into an input with no pull, writing 0 drives it low.
                # Measured on the Zero W: 38 us per write against 529 us
                # for the claim-free-claim a pass used to do per row, which
                # was most of the keypad thread's cost.
                for row in self._row_nums:
                    lgpio.gpio_free(self._h, row)
                    lgpio.gpio_claim_output(
                        self._h, row, 1,
                        lgpio.SET_OPEN_DRAIN | lgpio.SET_PULL_NONE)

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
        if self._lg is not None:
            return self._events(self._scan_direct())
        down = set()
        for r, row in enumerate(self._rows):
            row.pin.function = "output"
            row.off()
            time.sleep(_SETTLE)
            for c, col in enumerate(self._cols):
                if col.value:
                    down.add((r, c))
            self._release(row)
        return self._events(down)

    def _scan_direct(self) -> set[tuple[int, int]]:
        """The same pass as scan(), straight through lgpio.

        Drive a row low, read the columns (pulled up, so a pressed key reads
        0), then release it -- which on an open-drain row is writing 1.

        No settle sleep here, unlike the gpiozero path. The write is an
        ioctl that returns ~38 us after the line has moved, against a settle
        time of a few microseconds through the key and the pull-up -- and
        time.sleep(50e-6) measured 190 us on the Zero W, more than the rest
        of the pass put together (1.30 ms with it, 0.55 ms without).
        """
        lg, h = self._lg, self._h
        down = set()
        for r, row in enumerate(self._row_nums):
            lg.gpio_write(h, row, 0)
            for c, col in enumerate(self._col_nums):
                if lg.gpio_read(h, col) == 0:
                    down.add((r, c))
            lg.gpio_write(h, row, 1)
        return down

    def _events(self, down: set[tuple[int, int]]) -> list[Event]:
        """Debounced presses for whatever changed since the last pass."""
        now = time.monotonic()
        events = []
        for key in sorted(down ^ self._down):          # anything that moved
            if now - self._changed.get(key, -1.0) < BOUNCE:
                continue
            self._changed[key] = now
            if key in down:                            # a press, not a release
                events.append(KEYPAD[key[0]][key[1]])
        for key, kind in KEYPAD_HELD.items():
            if key not in down:
                self._held_due.pop(key, None)
            elif key not in self._down:
                self._held_due[key] = now + HELD_REPEAT    # the press said it
            elif now >= self._held_due[key]:
                events.append(Event(kind))
                self._held_due[key] = now + HELD_REPEAT
        self._down = down
        return events

    def modes(self) -> str:
        """lgpio's view of every row, for the log line when a claim fails.

        'GPIO busy' on a line that `gpioinfo` reports as unclaimed means
        lgpio's own bookkeeping and the kernel's disagree, and the only way
        to tell which of the two is confused is to ask lgpio directly. The
        bits are its GPIO_IS_* flags: 0x100 claimed-input, 0x200
        claimed-output, 0x400 alert, and bit 0 set when the *kernel* holds
        the line — which is the one that says another process took it.

        Private gpiozero attributes on purpose: there is no public way to
        reach the chip handle, and a diagnostic that needs a released line
        to be reproducible is no diagnostic.
        """
        import lgpio
        out = []
        for row in self._rows:
            pin = row.pin
            try:
                mode = lgpio.gpio_get_mode(pin.factory._handle, pin._number)
                out.append(f"BCM{pin._number}={mode:#06x}")
            except Exception as exc:            # noqa: BLE001
                out.append(f"BCM{pin._number}=err({exc})")
        return " ".join(out)

    def release_all(self) -> None:
        """Best-effort Hi-Z on every row, for the recovery path in _scan_loop.

        Errors are swallowed on purpose: this runs *because* a claim already
        failed, and a row that cannot be released is the exact condition the
        caller is retrying against — raising here would replace the error
        being recovered from with a less informative one.
        """
        if self._lg is not None:
            for row in self._row_nums:
                try:
                    self._lg.gpio_write(self._h, row, 1)
                except Exception as exc:        # noqa: BLE001 - see docstring
                    log.debug("release of BCM%d failed: %s", row, exc)
            return
        for row in self._rows:
            try:
                self._release(row)
            except Exception as exc:            # noqa: BLE001 - see docstring
                log.debug("row %s would not release: %s", row.pin, exc)

    def close(self) -> None:
        for device in (*self._rows, *self._cols):
            device.close()


class GpioInput:
    """Every physical control, as one pollable source of Events."""

    def __init__(self):
        self._queue: deque[Event] = deque()
        # Written by the scan thread, drained by the app thread — the same
        # one-way channel as the events, and atomic for the same reason.
        self._fault = ""
        self._last_error = ""      # why the keypad stopped, for the journal
        self._matrix = _Matrix()
        self._buttons: list[Button] = []
        self._encoder: RotaryEncoder | None = None
        self._evdev: EvdevControls | None = None

        # The D-pad, the encoder push and the wheel come from the kernel's
        # own drivers when provision.sh has put the overlays in config.txt
        # (input_evdev.py says why). gpiozero remains as the fallback for a
        # board that has not been provisioned for that yet -- it works, at
        # the price of lgpio's alert thread, which is most of the app's idle
        # CPU on a Zero W.
        if EvdevControls.available():
            self._evdev = EvdevControls(self._queue)
        else:
            log.warning("kernel input devices not found; using gpiozero "
                        "callbacks (re-run provision.sh and reboot)")
            self._gpiozero_controls()

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
        """Scan until asked to stop, and survive a scan that fails.

        Claiming a row can fail for reasons outside this process. The BCM
        lines are a single system-wide resource, so anything else that opens
        them — a stray `pytest -m device`, a second copy of the app, a bench
        script — owns them until it exits, and lgpio raises 'GPIO busy'.

        Unhandled, that ends this thread while the app keeps running: the
        keypad goes dead, nothing on the panel says why, and the traceback
        lands on a console that SPEC decision 8 makes a projector. The device
        looks broken in the one way the operator cannot report.

        So a failed pass is retried instead. Contention is usually momentary
        and the next pass claims cleanly. If it does not, the rate drops to
        FAULT_PERIOD — there is no point spinning at 50 Hz fighting another
        process for a line it still holds — and the panel is told once, then
        told again if the keypad comes back.
        """
        failures = 0
        while not self._stop.is_set():
            try:
                for event in self._matrix.scan():
                    self._queue.append(event)
            except Exception as exc:            # noqa: BLE001 - see docstring
                failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                if failures == FAULT_AFTER:
                    self._fault = MSG_KEYPAD_LOST
                    log.warning("keypad scan failing: %s | rows: %s",
                                self._last_error, self._matrix.modes())
                # A pass that died partway can leave a row still driven low,
                # which reads as that whole row held down once scanning
                # resumes. Put every row back to Hi-Z before trying again.
                self._matrix.release_all()
            else:
                if failures >= FAULT_AFTER:
                    self._fault = MSG_KEYPAD_BACK
                    log.warning("keypad recovered after %d failed scans",
                                failures)
                failures = 0
            self._stop.wait(FAULT_PERIOD if failures >= FAULT_AFTER
                            else 1.0 / SCAN_HZ)

    def _gpiozero_controls(self) -> None:
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

    def take_fault(self) -> str:
        """Any keypad fault message the panel has not shown yet, or "".

        Returned once and cleared, so the message flashes on the transition —
        keypad lost, keypad back — rather than on every tick in between.
        """
        message, self._fault = self._fault, ""
        return message

    def close(self) -> None:
        self._stop.set()
        self._scanner.join(timeout=1.0)
        self._matrix.close()
        if self._evdev is not None:
            self._evdev.close()
        if self._encoder is not None:
            self._encoder.close()
        for button in self._buttons:
            button.close()
