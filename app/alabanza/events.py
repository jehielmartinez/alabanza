"""Input events — the one vocabulary every input backend translates into.

The physical controls are deliberately few (see docs/SPEC.md):

    keypad     0-9  *  #                    (3x4, no letter keys)
    buttons    a D-pad: ◀ ▶ seek, ▲ ▼ up/down, centre = Play/Pause
    encoder    wheel + push

Events are *what the operator did*, not what it means — `UP` is the Up button,
and only the app knows whether that browses hymns or nudges the speed. The
keyboard backend (dev) and the GPIO backend (device) both emit these.
"""

from dataclasses import dataclass
from enum import Enum, auto


class Kind(Enum):
    DIGIT = auto()        # keypad 0-9; value: the digit
    STAR = auto()         # keypad * — back / erase / stop
    CONFIRM = auto()      # keypad # — confirm the selection
    PLAY_PAUSE = auto()
    SEEK_BACK = auto()
    SEEK_FWD = auto()
    UP = auto()           # Up button    — browse, speed, list
    DOWN = auto()         # Down button
    WHEEL_CW = auto()     # encoder clockwise — volume up, list down
    WHEEL_CCW = auto()    # encoder counter-clockwise
    PUSH = auto()         # encoder push — menu / select
    RESCAN = auto()       # dev convenience: rescan library
    QUIT = auto()         # dev convenience: exit app


@dataclass(frozen=True)
class Event:
    kind: Kind
    value: int = 0
