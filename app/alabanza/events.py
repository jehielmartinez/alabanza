"""Input events — the one vocabulary every input backend translates into.

The keyboard backend (Phase 0) and the GPIO backend (Phase 1) both emit
these; the app state machine only ever sees Events.
"""

from dataclasses import dataclass
from enum import Enum, auto


class Kind(Enum):
    DIGIT = auto()        # value: 0-9
    STAR = auto()         # keypad * — clear / backspace
    CONFIRM = auto()      # keypad # — confirm selection / select menu item
    PLAY_PAUSE = auto()
    STOP = auto()
    SEEK_BACK = auto()
    SEEK_FWD = auto()
    SPEED_DOWN = auto()
    SPEED_UP = auto()
    MENU = auto()         # menu/back button
    SEARCH = auto()       # keypad A — T9 title search
    ENC_UP = auto()       # encoder clockwise
    ENC_DOWN = auto()     # encoder counter-clockwise
    ENC_PUSH = auto()     # encoder push
    RESCAN = auto()       # dev convenience: rescan library
    QUIT = auto()         # dev convenience: exit app


@dataclass(frozen=True)
class Event:
    kind: Kind
    value: int = 0
