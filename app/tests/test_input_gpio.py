"""The keypad scan thread's failure behaviour.

The BCM lines are a system-wide resource, so a row claim can fail because
something *else* took it — and the scan runs on its own thread, where an
unhandled exception is silent. These pin down that a failed scan is retried
rather than fatal, and that a keypad which stays gone reaches the panel.

No hardware and no Pi: the matrix is scripted and the loop is run straight
through on the calling thread. gpiozero is still imported by the module under
test, so this skips where the device extra is not installed.
"""

import threading
from collections import deque

import pytest

pytest.importorskip("gpiozero")

from alabanza import input_gpio                                    # noqa: E402
from alabanza.events import Event, Kind                            # noqa: E402
from alabanza.input_gpio import GpioInput                          # noqa: E402

FAIL = "fail"
PRESS = Event(Kind.DIGIT, 7)


class ScriptedMatrix:
    """A keypad that fails on cue, then ends the loop when the script runs out.

    `drain` stands in for the app thread calling take_fault() once a tick, so
    a message that is overwritten before anyone could have seen it is a test
    failure rather than an invisible pass.
    """

    def __init__(self, script, stop, drain):
        self._script = list(script)
        self._stop = stop
        self._drain = drain
        self._failing = False
        self.released = 0

    def modes(self) -> str:
        """The log line on the FAULT_AFTER-th failure asks the matrix for
        lgpio's view of the rows. A scripted keypad has no rows to report,
        and it must not blow up in the except handler the test is about."""
        return "scripted"

    def scan(self):
        self._drain()
        if not self._script:
            # Out of script: stop the loop, but keep behaving the way the last
            # step did. Returning a clean empty scan here would look exactly
            # like the keypad recovering, and the loop would rightly report it.
            self._stop.set()
            if self._failing:
                raise RuntimeError("'GPIO busy'")
            return []
        step = self._script.pop(0)
        self._failing = step is FAIL
        if self._failing:
            raise RuntimeError("'GPIO busy'")
        return [step]

    def release_all(self):
        self.released += 1


def run(script, monkeypatch, fault_after=3):
    """Run the real _scan_loop over a scripted matrix, as fast as it will go."""
    monkeypatch.setattr(input_gpio, "FAULT_AFTER", fault_after)
    monkeypatch.setattr(input_gpio, "FAULT_PERIOD", 0.0)
    monkeypatch.setattr(input_gpio, "SCAN_HZ", 1_000_000)

    controls = GpioInput.__new__(GpioInput)     # no pins, no threads
    controls._queue = deque()
    controls._stop = threading.Event()
    controls._fault = ""

    seen: list[str] = []
    matrix = ScriptedMatrix(script, controls._stop,
                            lambda: seen.append(controls.take_fault()))
    controls._matrix = matrix

    controls._scan_loop()
    seen.append(controls.take_fault())
    return controls, matrix, [message for message in seen if message]


class TestAFailedScanIsNotFatal:
    def test_a_momentary_failure_keeps_the_keypad_alive(self, monkeypatch):
        """One 'GPIO busy' used to end the thread and take the keypad with
        it, leaving an app that ran perfectly and ignored every key."""
        controls, _, faults = run([FAIL, PRESS], monkeypatch)
        assert controls.poll() == [PRESS], "the press after a failure was lost"
        assert faults == [], "a single blip should not reach the operator"

    def test_the_rows_are_released_before_retrying(self, monkeypatch):
        """A pass that dies partway can leave a row driven low, which the
        next scan reads as that entire row held down."""
        _, matrix, _ = run([FAIL, PRESS], monkeypatch)
        assert matrix.released == 1

    def test_presses_keep_arriving_across_repeated_failures(self, monkeypatch):
        _, _, _ = run([FAIL] * 10, monkeypatch)       # must simply return
        controls, _, _ = run([FAIL, PRESS, FAIL, PRESS], monkeypatch)
        assert controls.poll() == [PRESS, PRESS]


class TestAKeypadThatStaysGoneReachesThePanel:
    def test_it_is_reported_once_it_is_really_gone(self, monkeypatch):
        _, _, faults = run([FAIL] * 6, monkeypatch, fault_after=3)
        assert faults == [input_gpio.MSG_KEYPAD_LOST], \
            "a keypad that stopped answering must say so, and say it once"

    def test_coming_back_is_reported_too(self, monkeypatch):
        """Otherwise the panel keeps warning about a keypad that works."""
        _, _, faults = run([FAIL] * 4 + [PRESS], monkeypatch, fault_after=3)
        assert faults == [input_gpio.MSG_KEYPAD_LOST,
                          input_gpio.MSG_KEYPAD_BACK]

    def test_the_message_fits_the_panel(self):
        from alabanza.app import MSG_CHARS
        for message in (input_gpio.MSG_KEYPAD_LOST, input_gpio.MSG_KEYPAD_BACK):
            assert len(message) <= MSG_CHARS, f"{message!r} is too wide"


class TestTheHardwareTestAgreesWithTheKeypad:
    """hwtest.py writes the 3x4 legend down a second time, because importing
    this module to draw a screen would drag gpiozero onto a laptop. That is
    the same bargain the pin map makes, and it holds only while something
    checks it — a legend that drifts would have the tool confidently print
    the wrong key for a correctly wired board."""

    def test_every_key_matches_the_event_the_matrix_emits(self):
        from alabanza.hwtest import KEYPAD_LAYOUT, control_for
        from alabanza.input_gpio import KEYPAD
        from alabanza.pins import KEYPAD_COLS, KEYPAD_ROWS

        assert len(KEYPAD) == len(KEYPAD_LAYOUT)
        for r, (events, legend) in enumerate(zip(KEYPAD, KEYPAD_LAYOUT)):
            assert len(events) == len(legend)
            for c, (event, char) in enumerate(zip(events, legend)):
                control = control_for(event)
                assert control is not None, f"{event} names no control"
                assert control.glyph == char, \
                    f"row {r} col {c}: matrix says {control.glyph}, legend {char}"
                assert control.pins == (KEYPAD_ROWS[r], KEYPAD_COLS[c])
