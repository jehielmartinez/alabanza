"""The D-pad, the encoder push and the encoder wheel, read from the kernel.

Seven controls used to be seven gpiozero objects, each an edge callback
through lgpio's alert thread -- which on the Zero W costs 12-15% of the only
core with a single callback registered and no edges at all: it polls the
event descriptors with a tiny timeout. The kernel already has drivers for
exactly these devices, `gpio-keys` and `rotary-encoder`, both interrupt
driven; Pi OS ships overlays for them (provision.sh puts them in config.txt),
and the result is a couple of `/dev/input/event*` nodes that deliver a key
down, a key up or a wheel step as a 16-byte record when -- and only when --
something happened. Reading them is a `select()` that sleeps.

Two things are kept out of the kernel on purpose. Debounce and hold timing
happen here, in `KeyLogic`, which is pure: it takes (code, value, now) and
answers with Events, so every rule can be tested on a laptop. And the wheel's
detent count per quadrature period is a property of the encoder, set in the
overlay (`steps-per-period`) and verified on the bench, not guessed here.

Discovery is by bus and capability, not by name: devices on the host bus
(where gpio-keys and rotary-encoder register) that advertise our key codes
or a relative X axis are ours. The bus check is not optional: the vc4 HDMI
CEC device advertises the whole keyboard and a wheel, and a Bluetooth
speaker's AVRCP remote shows up with the arrow keys and Enter -- both were
matched on the first try, and the real D-pad went dead.
"""

import logging
import os
import select
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .events import Event, Kind

log = logging.getLogger(__name__)

# linux/input-event-codes.h -- the handful this device uses.
EV_KEY, EV_REL = 0x01, 0x02
REL_X = 0x00
KEY_ENTER, KEY_UP, KEY_LEFT, KEY_RIGHT, KEY_DOWN, KEY_MENU = 28, 103, 105, 106, 108, 139

# struct input_event: two C longs (the timeval), then type, code, value.
# 16 bytes on the 32-bit Pi OS the Zero W runs, 24 on 64-bit; native sizes
# are what the kernel writes, so the format is native on purpose.
_EVENT = struct.Struct("llHHi")

BOUNCE = 0.02        # a change within this of the last one on that key is bounce
SEEK_REPEAT = 0.4    # held ◀/▶ repeats at this interval (SPEC: "held = repeat")
HELD_REPEAT = 0.25   # how often a held encoder push re-announces itself

# +1 when a positive REL_X step is clockwise. It depends on which channel is
# wired as A; verified on the bench with the real board.
WHEEL_SIGN = 1

BUS_HOST = 0x19      # linux/input.h: gpio-keys and rotary-encoder register here

INPUT_SYSFS = Path("/sys/class/input")
INPUT_DEV = Path("/dev/input")


@dataclass(frozen=True)
class KeySpec:
    kind: Kind                     # on the way down
    release: Kind | None = None    # on the way up, if anyone cares
    held: Kind | None = None       # keepalive while down, every HELD_REPEAT
    repeat: bool = False           # re-emit `kind` every SEEK_REPEAT while down


# The key codes are arbitrary -- the app never sees them -- but they are the
# same ones provision.sh writes into config.txt, so keep the two in step.
KEYS: dict[int, KeySpec] = {
    KEY_ENTER: KeySpec(Kind.PLAY_PAUSE),
    KEY_UP: KeySpec(Kind.UP),
    KEY_DOWN: KeySpec(Kind.DOWN),
    KEY_LEFT: KeySpec(Kind.SEEK_BACK, repeat=True),
    KEY_RIGHT: KeySpec(Kind.SEEK_FWD, repeat=True),
    KEY_MENU: KeySpec(Kind.PUSH, release=Kind.PUSH_RELEASE, held=Kind.PUSH_HELD),
}


class KeyLogic:
    """Turns raw key and wheel records into Events, with debounce and holds.

    The hold semantics match what the gpiozero backend emitted, because the
    app was written against them: a repeating key re-emits its own kind
    every SEEK_REPEAT for as long as it is down (the first repeat one
    interval after the press), and the encoder push sends PUSH_HELD every
    HELD_REPEAT as a keepalive -- the app times the three-second shutdown
    hold itself and gives up when the keepalives stop, so a backend that
    never reports release is still safe.
    """

    def __init__(self, keys: dict[int, KeySpec] = KEYS, wheel_sign: int = WHEEL_SIGN):
        self._keys = keys
        self._sign = wheel_sign
        self._down: dict[int, float] = {}       # code -> when the next repeat is due
        self._changed: dict[int, float] = {}    # code -> last accepted edge

    def feed(self, etype: int, code: int, value: int, now: float) -> list[Event]:
        if etype == EV_REL and code == REL_X:
            kind = Kind.WHEEL_CW if value * self._sign > 0 else Kind.WHEEL_CCW
            return [Event(kind)] * abs(value)
        if etype != EV_KEY or code not in self._keys or value == 2:
            return []                           # 2 is the kernel's own autorepeat
        if now - self._changed.get(code, -1.0) < BOUNCE:
            return []
        self._changed[code] = now
        spec = self._keys[code]
        if value:
            self._down[code] = now + (HELD_REPEAT if spec.held else SEEK_REPEAT)
            return [Event(spec.kind)]
        self._down.pop(code, None)
        return [Event(spec.release)] if spec.release else []

    def due(self, now: float) -> list[Event]:
        """Whatever a held key owes by `now`: repeats and keepalives."""
        events = []
        for code, when in list(self._down.items()):
            if now < when:
                continue
            spec = self._keys[code]
            if spec.repeat:
                events.append(Event(spec.kind))
                self._down[code] = now + SEEK_REPEAT
            elif spec.held:
                events.append(Event(spec.held))
                self._down[code] = now + HELD_REPEAT
            else:
                del self._down[code]            # nothing to say while it is held
        return events

    def next_due(self, now: float) -> float | None:
        """Seconds until the earliest repeat, or None if nothing is held."""
        if not self._down:
            return None
        return max(0.0, min(self._down.values()) - now)


def decode(data: bytes):
    """(type, code, value) for each whole record in a read()."""
    size = _EVENT.size
    for offset in range(0, len(data) - size + 1, size):
        _, _, etype, code, value = _EVENT.unpack_from(data, offset)
        yield etype, code, value


def _has_bit(mask: str, bit: int) -> bool:
    """sysfs capability masks: space-separated hex words, most significant
    first, so the last word holds bits 0..(wordsize-1)."""
    words = mask.split()
    if not words:
        return False
    width = 32 if len(words[-1]) <= 8 else 64
    index = bit // width
    if index >= len(words):
        return False
    return bool(int(words[-1 - index], 16) >> (bit % width) & 1)


def discover(sysfs: Path = INPUT_SYSFS, devdir: Path = INPUT_DEV) -> dict[Path, str]:
    """The event nodes that carry our controls: {device node: what it has}."""
    found = {}
    for entry in sorted(sysfs.glob("event*")):
        caps = entry / "device" / "capabilities"
        try:
            bus = int((entry / "device" / "id" / "bustype").read_text(), 16)
            keys = (caps / "key").read_text()
            rel = (caps / "rel").read_text()
            name = (entry / "device" / "name").read_text().strip()
        except (OSError, ValueError):
            continue
        if bus != BUS_HOST:
            continue
        has = [f"key {c}" for c in KEYS if _has_bit(keys, c)]
        if _has_bit(rel, REL_X):
            has.append("wheel")
        node = devdir / entry.name
        if has and node.exists():
            found[node] = f"{name}: {', '.join(has)}"
    return found


class EvdevControls:
    """The seven non-matrix controls, as Events on a queue.

    One thread, asleep in select() until the kernel has something or a held
    key owes a repeat. `available()` says whether the overlays are loaded at
    all, so the caller can fall back to gpiozero on a board that has not
    been provisioned for this yet.
    """

    @staticmethod
    def available() -> bool:
        return bool(discover())

    def __init__(self, queue: deque[Event]):
        self._queue = queue
        self._logic = KeyLogic()
        self._fds: dict[int, Path] = {}
        for node, what in discover().items():
            self._fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
            log.info("controls: %s (%s)", node, what)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="alabanza-controls")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            timeout = self._logic.next_due(now)
            ready, _, _ = select.select(list(self._fds), [], [],
                                        0.5 if timeout is None else min(timeout, 0.5))
            now = time.monotonic()
            for fd in ready:
                try:
                    data = os.read(fd, _EVENT.size * 64)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    # The node went away (an overlay unloaded?): drop it and
                    # keep serving the rest rather than dying quietly.
                    log.warning("controls: %s: %s", self._fds.pop(fd), exc)
                    os.close(fd)
                    continue
                for etype, code, value in decode(data):
                    self._queue.extend(self._logic.feed(etype, code, value, now))
            self._queue.extend(self._logic.due(now))
            if not self._fds:
                log.error("controls: every input device is gone")
                return

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        for fd in list(self._fds):
            os.close(fd)
        self._fds.clear()
