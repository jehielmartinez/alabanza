"""The pin map, guarded.

This table is what a PCB gets fabricated from, and a wrong entry is invisible
until boards arrive two weeks later. It used to live in three places — the
build plan, input_gpio.py and the device tests — so these check the one
remaining copy is sane and that the document still agrees with it.
"""

import re
from pathlib import Path

from alabanza import pins

DOC = Path(__file__).resolve().parents[2] / "docs" / "BUILD-PLAN.md"


def _documented() -> dict[str, list[int]]:
    """The pin map table from BUILD-PLAN.md, as {row label: [bcm numbers]}."""
    rows = {}
    for line in DOC.read_text().splitlines():
        match = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", line)
        if not match:
            continue
        label, values = match.groups()
        numbers = [int(n) for n in re.findall(r"\d+", values)]
        if numbers and not label.startswith("-"):
            rows[label] = numbers
    return rows


class TestTheMapIsInternallyConsistent:
    def test_no_pin_does_two_jobs(self):
        used = pins.ALL_CONTROL_PINS
        duplicates = {p for p in used if used.count(p) > 1}
        assert not duplicates, f"pins assigned twice: {sorted(duplicates)}"

    def test_controls_never_touch_the_i2c_bus(self):
        """GPIO 2 and 3 carry the OLED, and have fixed 1.8k pull-ups that
        cannot be turned off — a control there would never read correctly."""
        assert not {pins.I2C_SDA, pins.I2C_SCL} & set(pins.ALL_CONTROL_PINS)

    def test_the_debug_uart_stays_free(self):
        """BUILD-PLAN reserves 14/15 deliberately; taking them costs the only
        way to see a boot failure on a device with no console."""
        assert not set(pins.UART_RESERVED) & set(pins.ALL_CONTROL_PINS)

    def test_spare_pins_are_actually_spare(self):
        assert not set(pins.SPARE) & set(pins.ALL_CONTROL_PINS)

    def test_every_pin_is_a_real_bcm_number(self):
        every = (*pins.ALL_CONTROL_PINS, pins.I2C_SDA, pins.I2C_SCL,
                 *pins.UART_RESERVED, *pins.SPARE)
        assert all(0 <= p <= 27 for p in every), sorted(every)

    def test_the_count_matches_what_the_plan_claims(self):
        """BUILD-PLAN says "17 pins used, 7 spare" — 15 controls plus I2C."""
        assert len(pins.ALL_CONTROL_PINS) == 15
        assert len(pins.ALL_CONTROL_PINS) + 2 == 17
        assert len(pins.SPARE) == 7


class TestTheDocumentAgrees:
    """BUILD-PLAN.md calls itself the source of truth and HARDWARE.md
    translates it to header pins, so a silent drift between the prose and the
    code is a mis-fabricated board."""

    def test_the_keypad_matches(self):
        doc = _documented()
        assert doc["Keypad rows"] == list(pins.KEYPAD_ROWS)
        assert doc["Keypad columns"] == list(pins.KEYPAD_COLS)

    def test_the_encoder_matches(self):
        doc = _documented()
        assert doc["Encoder A / B / push"] == [
            pins.ENCODER_A, pins.ENCODER_B, pins.ENCODER_PUSH]

    def test_the_dpad_matches(self):
        doc = _documented()
        assert doc["D-pad centre (Play/Pause)"] == [pins.DPAD_CENTRE]
        assert doc["D-pad ◀ / ▶"] == [pins.DPAD_LEFT, pins.DPAD_RIGHT]
        assert doc["D-pad ▲ / ▼"] == [pins.DPAD_UP, pins.DPAD_DOWN]

    def test_the_reserved_and_spare_lists_match(self):
        doc = _documented()
        assert doc["Reserved (debug UART)"] == list(pins.UART_RESERVED)
        assert doc["Spare"] == list(pins.SPARE)
