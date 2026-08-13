"""Keyboard input backend (Phase 0): curses keys -> Events.

Stand-ins for the physical controls:
  0-9        keypad digits          #  or Enter  keypad #  (confirm)
  *  or ⌫    keypad *  (back)       Space        D-pad centre (play/pause)
  ← →        D-pad seek             ↑ ↓          D-pad up / down
  - / +      encoder wheel          m            encoder push (opens the menu)
  r          rescan library         q            quit (dev only)
"""

import curses

from .events import Event, Kind

_SIMPLE = {
    ord(" "): Kind.PLAY_PAUSE,
    curses.KEY_LEFT: Kind.SEEK_BACK,
    curses.KEY_RIGHT: Kind.SEEK_FWD,
    curses.KEY_UP: Kind.UP,
    curses.KEY_DOWN: Kind.DOWN,
    ord("-"): Kind.WHEEL_CCW,
    ord("+"): Kind.WHEEL_CW,
    ord("="): Kind.WHEEL_CW,
    ord("m"): Kind.PUSH,
    ord("*"): Kind.STAR,
    curses.KEY_BACKSPACE: Kind.STAR,
    ord("\x7f"): Kind.STAR,
    ord("#"): Kind.CONFIRM,
    ord("\n"): Kind.CONFIRM,
    curses.KEY_ENTER: Kind.CONFIRM,
    ord("r"): Kind.RESCAN,
    ord("q"): Kind.QUIT,
}


def read_event(screen: "curses.window") -> Event | None:
    """Non-blocking read of one input event (None if no key pressed)."""
    key = screen.getch()
    if key == -1:
        return None
    if ord("0") <= key <= ord("9"):
        return Event(Kind.DIGIT, key - ord("0"))
    kind = _SIMPLE.get(key)
    return Event(kind) if kind else None
