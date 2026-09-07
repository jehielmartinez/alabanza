"""Bluetooth: the one interface the app talks to, and the state it sees.

Design and rationale: docs/BLUETOOTH.md.

Commands are fire-and-forget and state() is a cheap immutable snapshot, so
nothing here can block the 50 ms tick loop — a BlueZ Connect() can hang for
half a minute. Results come back as data (a bumped `seq`), not callbacks, which
keeps app.py the pure synchronous state machine it is today.

Implementations: bt_fake.FakeBackend (dev machine), bt_bluez.BluezBackend
(device), NullBackend (no adapter, or Bluetooth switched off).
"""

from dataclasses import dataclass
from typing import Protocol

# The app times operations out itself rather than trusting a backend to return.
TIMEOUTS = {"pair": 30.0, "connect": 15.0, "disconnect": 5.0, "forget": 5.0}

SCAN_SECONDS = 30.0                   # discovery auto-stop
RECONNECT_DELAYS = (0.0, 5.0, 15.0)   # boot / loss recovery: 3 attempts, then quit

OP_LABELS = {
    "pair": "Emparejando",
    "connect": "Conectando",
    "disconnect": "Desconectando",
    "forget": "Olvidando",
}

# Every failure reaches the OLED as one short Spanish string sized for 128 px.
ERR_PAIR = "Fallo al emparejar"
ERR_CANCELED = "Emparejado cancelado"
ERR_NO_AUDIO = "No acepta audio"
ERR_CONNECT = "No se pudo conectar"
ERR_OFF = "Bluetooth apagado"
ERR_TIMEOUT = "Sin respuesta"


A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"

# Major Class-of-Device values that a speaker never reports.
#
# The inverse — a list of classes a speaker *does* report — is what was here
# before, and it does not survive real hardware: cheap speakers ship with a
# copy-pasted Class of Device. The one this was found on is a "RuggedLife
# Speaker ESR103PM" that identifies as major class 0x05, Peripheral, with
# Icon "input-keyboard". It would never have appeared in the menu, which
# takes out the primary audio route entirely.
#
# Phones and computers, by contrast, do not lie about being phones and
# computers — so excluding what we are sure of, rather than admitting only
# what we recognise, keeps SPEC.md's "a volunteer must not page through
# thirty phones" while still finding the speaker that misdescribes itself.
NOT_A_SPEAKER = frozenset({
    0x01,   # Computer
    0x02,   # Phone
    0x03,   # LAN / network access point
    0x06,   # Imaging: printer, scanner, camera
    0x09,   # Health
})


def is_audio(props: dict) -> bool:
    """A speaker, not somebody's phone, from BlueZ's device properties.

    Three tiers, most authoritative first:

    1. UUIDs contain A2DP Sink. Certain — but BlueZ only resolves UUIDs after
       connecting, so during discovery this is almost never available.
    2. UUIDs known and lacking A2DP: believe them, unless we paired it, since
       we only ever pair speakers.
    3. UUIDs unresolved, so fall back to the Class of Device. **No Class at
       all means the device was seen only over BLE**, and A2DP is a BR/EDR
       profile — it cannot be a speaker however loudly it advertises. That
       one check removes the phones, watches and trackers that make up the
       bulk of a scan in a populated room.
    """
    uuids = [u.lower() for u in props.get("UUIDs", [])]
    if A2DP_SINK in uuids:
        return True
    if uuids:                                  # knows its profiles, lacks A2DP
        return bool(props.get("Paired"))       # we only ever pair speakers
    cls = props.get("Class")
    if cls is None:
        return False                           # BLE-only advertiser
    return ((cls >> 8) & 0x1F) not in NOT_A_SPEAKER


@dataclass(frozen=True)
class BtDevice:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False
    audio: bool = True          # advertises A2DP Sink; anything else is hidden
    rssi: int | None = None


@dataclass(frozen=True)
class BtResult:
    """One finished operation. The app flashes a message when `seq` changes."""

    seq: int
    op: str                     # pair | connect | disconnect | forget
    mac: str
    ok: bool
    error: str = ""             # already a short, screen-sized Spanish string


@dataclass(frozen=True)
class BtState:
    available: bool = False     # adapter present and powered
    scanning: bool = False
    devices: tuple[BtDevice, ...] = ()
    busy_op: str = ""           # "" when idle
    busy_mac: str = ""
    busy_since: float = 0.0     # monotonic, drives the elapsed counter
    last_result: BtResult | None = None

    def device(self, mac: str) -> BtDevice | None:
        return next((d for d in self.devices if d.mac == mac), None)

    @property
    def connected_mac(self) -> str:
        return next((d.mac for d in self.devices if d.connected), "")


def visible(devices: tuple[BtDevice, ...]) -> list[BtDevice]:
    """What the Bluetooth list shows: audio devices only, paired first, then
    by signal strength. A volunteer scanning in a full church must not page
    through thirty phones and laptops."""
    return sorted(
        (d for d in devices if d.audio),
        key=lambda d: (not d.paired, -(d.rssi if d.rssi is not None else -999), d.name),
    )


class BluetoothBackend(Protocol):
    """Every command returns immediately; progress shows up in state().

    `pair` means "use this speaker": it pairs, trusts, and connects, and
    reports a single result — one user intent, one outcome.
    `cancel` abandons the running operation silently (the app has already
    said why); it never produces a result.
    """

    def state(self) -> BtState: ...
    def scan(self, on: bool) -> None: ...
    def pair(self, mac: str) -> None: ...
    def connect(self, mac: str) -> None: ...
    def disconnect(self, mac: str) -> None: ...
    def forget(self, mac: str) -> None: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...


class NullBackend:
    """No adapter. Every screen still works; nothing is ever available."""

    def state(self) -> BtState:
        return BtState()

    def scan(self, on: bool) -> None: ...
    def pair(self, mac: str) -> None: ...
    def connect(self, mac: str) -> None: ...
    def disconnect(self, mac: str) -> None: ...
    def forget(self, mac: str) -> None: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...
