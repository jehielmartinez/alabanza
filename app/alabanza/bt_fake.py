"""Fake Bluetooth backend: the whole flow on a dev machine, no BlueZ.

Bluetooth breaks in the field, not on the bench, so the roster below models the
failures actually worth rehearsing: a speaker that drops mid-hymn, one that
refuses to pair, one that never answers, and a phone that must never appear in
the list at all.

No threads: the simulation advances only when the app polls state(), so a given
sequence of key presses always produces the same run.
"""

import time
from dataclasses import dataclass

from .bluetooth import ERR_CONNECT, ERR_PAIR, BtDevice, BtResult, BtState

NEVER = float("inf")


@dataclass
class _Fake:
    mac: str
    name: str
    audio: bool = True
    rssi: int = -60
    appears_after: float = 0.0   # seconds of scanning before it shows up
    pair_delay: float = 4.0
    connect_delay: float = 2.5
    pair_fails: bool = False     # refuses pairing, every time
    connect_hangs: bool = False  # never answers — exercises the app timeout
    drops_after: float = 0.0     # seconds connected, then it vanishes — once,
                                 # so recovery can be rehearsed to the end


ROSTER = (
    _Fake("AA:BB:CC:00:00:01", "JBL Flip 5", rssi=-45, appears_after=0.5),
    _Fake("AA:BB:CC:00:00:02", "Bocina Iglesia", rssi=-55, appears_after=2.0,
          drops_after=20.0),
    _Fake("AA:BB:CC:00:00:03", "Soundcore 2", rssi=-70, appears_after=3.5,
          pair_fails=True),
    _Fake("AA:BB:CC:00:00:04", "Bocina Vieja", rssi=-80, appears_after=5.0,
          connect_hangs=True),
    _Fake("AA:BB:CC:00:00:05", "iPhone de Ana", audio=False, rssi=-50,
          appears_after=1.0),
)

# One speaker starts out paired, the way a device that has seen a service does.
PREPAIRED = ("AA:BB:CC:00:00:01",)


@dataclass
class _Op:
    op: str
    mac: str
    started: float
    done_at: float
    ok: bool
    error: str = ""


class FakeBackend:
    def __init__(self, roster=ROSTER, paired=PREPAIRED, available: bool = True,
                 clock=time.monotonic):
        self._now = clock
        self.roster = {f.mac: f for f in roster}
        self._paired: set[str] = set(paired)
        self._seen: set[str] = set()
        self._dropped: set[str] = set()
        self._connected = ""
        self._connected_since = 0.0
        self._scanning_since: float | None = None
        self._op: _Op | None = None
        self._seq = 0
        self._result: BtResult | None = None
        self._available = available

    # -- simulation ----------------------------------------------------
    def _finish(self, op: _Op) -> None:
        if op.ok:
            if op.op in ("pair", "connect"):
                self._paired.add(op.mac)
                self._connected = op.mac
                self._connected_since = self._now()
            elif op.op == "disconnect":
                self._connected = ""
            elif op.op == "forget":
                self._paired.discard(op.mac)
                self._seen.discard(op.mac)
                if self._connected == op.mac:
                    self._connected = ""
        self._seq += 1
        self._result = BtResult(self._seq, op.op, op.mac, op.ok, op.error)
        self._op = None

    def _advance(self) -> None:
        now = self._now()
        if self._scanning_since is not None:
            elapsed = now - self._scanning_since
            self._seen |= {f.mac for f in self.roster.values()
                           if f.appears_after <= elapsed}
        if self._op and now >= self._op.done_at:
            self._finish(self._op)
        if self._connected and self._connected not in self._dropped:
            fake = self.roster[self._connected]
            if fake.drops_after and now - self._connected_since >= fake.drops_after:
                self._dropped.add(self._connected)
                self._connected = ""     # the speaker walked away, unannounced

    # -- BluetoothBackend ----------------------------------------------
    def state(self) -> BtState:
        self._advance()
        macs = self._paired | self._seen
        devices = tuple(
            BtDevice(
                mac=f.mac, name=f.name,
                paired=f.mac in self._paired,
                connected=f.mac == self._connected,
                audio=f.audio, rssi=f.rssi,
            )
            for f in (self.roster[m] for m in sorted(macs))
        )
        return BtState(
            available=self._available,
            scanning=self._scanning_since is not None,
            devices=devices,
            busy_op=self._op.op if self._op else "",
            busy_mac=self._op.mac if self._op else "",
            busy_since=self._op.started if self._op else 0.0,
            last_result=self._result,
        )

    def scan(self, on: bool) -> None:
        if not self._available:
            return
        self._scanning_since = self._now() if on else None

    def _start(self, op: str, mac: str, delay: float, ok: bool, error: str = "") -> None:
        if self._op or mac not in self.roster:
            return
        now = self._now()
        self._op = _Op(op, mac, now, now + delay, ok, error)

    def pair(self, mac: str) -> None:
        f = self.roster.get(mac)
        if not f:
            return
        # pair chains into connect: one intent, one result
        delay = f.pair_delay + (0 if f.pair_fails else f.connect_delay)
        self._start("pair", mac, NEVER if f.connect_hangs else delay,
                    not f.pair_fails, ERR_PAIR if f.pair_fails else "")

    def connect(self, mac: str) -> None:
        f = self.roster.get(mac)
        if not f:
            return
        self._start("connect", mac, NEVER if f.connect_hangs else f.connect_delay,
                    True, "" if not f.connect_hangs else ERR_CONNECT)

    def disconnect(self, mac: str) -> None:
        self._start("disconnect", mac, 0.4, True)

    def forget(self, mac: str) -> None:
        self._start("forget", mac, 0.3, True)

    def cancel(self) -> None:
        self._op = None          # silent: the app has already said why

    def close(self) -> None:
        self._scanning_since = None
        self._op = None
