"""The GPIO pin map — the one place it lives.

BCM numbering. [docs/BUILD-PLAN.md](../../docs/BUILD-PLAN.md) presents the same
map for humans and HARDWARE.md translates it to physical header pins; this
module is what the code actually uses, and `tests/test_pins.py` checks that all
three still agree.

Nothing is imported here on purpose. A pin map that pulls in gpiozero can only
be read on a Pi, which is how it ended up copied into the test suite in the
first place — and a copy is exactly what you do not want for a table that a
PCB is fabricated from.
"""

# --- controls -------------------------------------------------------------
KEYPAD_ROWS = (5, 6, 13, 19)
KEYPAD_COLS = (12, 16, 20)

ENCODER_A, ENCODER_B, ENCODER_PUSH = 17, 27, 22

DPAD_CENTRE = 23
DPAD_LEFT, DPAD_RIGHT = 25, 26
DPAD_UP, DPAD_DOWN = 7, 8

# --- buses ----------------------------------------------------------------
I2C_SDA, I2C_SCL = 2, 3

# --- must stay free -------------------------------------------------------
UART_RESERVED = (14, 15)          # debug UART, deliberately unused
SPARE = (4, 9, 10, 11, 18, 21, 24)

# Grouped for anything that reports per-peripheral — the device tests name the
# group whose pin failed, which is what makes "wire one at a time" work.
CONTROLS: dict[str, tuple[int, ...]] = {
    "keypad rows": KEYPAD_ROWS,
    "keypad columns": KEYPAD_COLS,
    "encoder A/B/push": (ENCODER_A, ENCODER_B, ENCODER_PUSH),
    "d-pad centre": (DPAD_CENTRE,),
    "d-pad left/right": (DPAD_LEFT, DPAD_RIGHT),
    "d-pad up/down": (DPAD_UP, DPAD_DOWN),
}

ALL_CONTROL_PINS = tuple(pin for pins in CONTROLS.values() for pin in pins)
