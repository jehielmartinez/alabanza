"""Keyboard input backend (Phase 0): curses keys -> Events.

Stand-ins for the physical controls:
  0-9        keypad digits          Enter / #   keypad # (confirm)
  *          keypad * (clear)       Space       Play/Pause button
  s          Stop button            Left/Right  Seek buttons
  - / +      Speed buttons          Up/Down     rotary encoder
  Enter      encoder push (menus)   m           Menu/Back button
  / or a     keypad A (T9 search)   r           rescan library
  q          quit (dev only)
"""

import curses

from .events import Event, Kind

_SIMPLE = {
    ord(" "): Kind.PLAY_PAUSE,
    ord("s"): Kind.STOP,
    curses.KEY_LEFT: Kind.SEEK_BACK,
    curses.KEY_RIGHT: Kind.SEEK_FWD,
    ord("-"): Kind.SPEED_DOWN,
    ord("+"): Kind.SPEED_UP,
    ord("="): Kind.SPEED_UP,
    ord("m"): Kind.MENU,
    ord("/"): Kind.SEARCH,
    ord("a"): Kind.SEARCH,
    curses.KEY_UP: Kind.ENC_UP,
    curses.KEY_DOWN: Kind.ENC_DOWN,
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
