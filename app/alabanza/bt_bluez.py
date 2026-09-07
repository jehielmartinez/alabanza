"""The real Bluetooth backend: BlueZ over D-Bus, via dbus-fast.

Everything here runs on a private thread with its own asyncio loop, because a
BlueZ Connect() can block for half a minute and the app's tick loop must never
wait. The app only ever touches `state()` (a lock-guarded snapshot) and the
fire-and-forget commands.

Reads come from ObjectManager plus signals — no per-property round trips — and
writes go out as raw messages, so no device ever has to be introspected.

Untested on hardware until a Pi with a real speaker is in front of it; the flows
it serves were developed against bt_fake.FakeBackend.
"""

import asyncio
import threading
import time

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

from .bluetooth import (
    ERR_CANCELED,
    ERR_CONNECT,
    ERR_NO_AUDIO,
    ERR_OFF,
    ERR_PAIR,
    BtDevice,
    BtResult,
    BtState,
    is_audio,
)

BLUEZ = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
AGENT_PATH = "/org/alabanza/agent"

# BlueZ error name / text fragment -> what the OLED says
_ERRORS = {
    "AuthenticationFailed": ERR_PAIR,
    "AuthenticationRejected": ERR_PAIR,
    "AuthenticationCanceled": ERR_CANCELED,
    "AuthenticationTimeout": ERR_PAIR,
    "br-connection-profile-unavailable": ERR_NO_AUDIO,
    "NotSupported": ERR_NO_AUDIO,
    "NotReady": ERR_OFF,
    "Blocked": ERR_OFF,
}


def _message(error: str) -> str:
    for needle, text in _ERRORS.items():
        if needle in error:
            return text
    return ERR_CONNECT


class _Agent(ServiceInterface):
    """BlueZ refuses to pair without an agent. Speakers are Just Works devices,
    so this one auto-confirms everything — the keypad never asks for a PIN."""

    def __init__(self):
        super().__init__("org.bluez.Agent1")

    @method()
    def Release(self): ...

    # the annotations are D-Bus type signatures, not Python types
    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"): ...  # noqa: F821

    @method()
    def RequestAuthorization(self, device: "o"): ...  # noqa: F821

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"): ...  # noqa: F821

    @method()
    def Cancel(self): ...


class BluezBackend:
    def __init__(self, adapter: str = "hci0"):
        self._adapter_path = f"/org/bluez/{adapter}"
        self._lock = threading.Lock()
        self._state = BtState()
        self._props: dict[str, dict] = {}      # object path -> device properties
        self._powered = False
        self._scanning = False
        self._busy: tuple[str, str, float] | None = None
        self._seq = 0
        self._result: BtResult | None = None
        self._task: asyncio.Task | None = None
        self._bus: MessageBus | None = None
        self._ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="alabanza-bluez")
        self._thread.start()
        self._ready.wait(timeout=5.0)          # never block the app for longer

    # -- snapshot ------------------------------------------------------
    def _publish(self) -> None:
        devices = tuple(
            BtDevice(
                mac=props.get("Address", ""),
                name=props.get("Alias") or props.get("Name") or props.get("Address", ""),
                paired=bool(props.get("Paired")),
                connected=bool(props.get("Connected")),
                audio=is_audio(props),
                rssi=props.get("RSSI"),
            )
            for props in self._props.values() if props.get("Address")
        )
        busy = self._busy or ("", "", 0.0)
        with self._lock:
            self._state = BtState(
                available=self._powered, scanning=self._scanning,
                devices=devices, busy_op=busy[0], busy_mac=busy[1],
                busy_since=busy[2], last_result=self._result,
            )

    def state(self) -> BtState:
        with self._lock:
            return self._state

    # -- thread / bus --------------------------------------------------
    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._setup())
        except Exception:
            self._ready.set()                  # no adapter: everything reports off
            return
        self._ready.set()
        self._loop.run_forever()

    async def _setup(self) -> None:
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._bus.export(AGENT_PATH, _Agent())
        await self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                         "os", [AGENT_PATH, "NoInputNoOutput"])
        await self._call("/org/bluez", "org.bluez.AgentManager1",
                         "RequestDefaultAgent", "o", [AGENT_PATH])
        await self._bus.call(Message(
            destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch", signature="s",
            body=[f"type='signal',sender='{BLUEZ}'"]))
        self._bus.add_message_handler(self._on_signal)

        reply = await self._call("/", "org.freedesktop.DBus.ObjectManager",
                                 "GetManagedObjects")
        for path, interfaces in reply.body[0].items():
            self._absorb(path, interfaces)
        await self._set_prop(self._adapter_path, ADAPTER_IFACE, "Powered",
                             Variant("b", True))
        self._publish()

    async def _call(self, path, interface, member, signature="", body=()):
        reply = await self._bus.call(Message(
            destination=BLUEZ, path=path, interface=interface, member=member,
            signature=signature, body=list(body)))
        if reply.message_type is MessageType.ERROR:
            raise RuntimeError(f"{reply.error_name}: {reply.body[0] if reply.body else ''}")
        return reply

    async def _set_prop(self, path, interface, name, value: Variant) -> None:
        await self._call(path, PROPS_IFACE, "Set", "ssv", [interface, name, value])

    @staticmethod
    def _unwrap(props: dict) -> dict:
        return {k: (v.value if isinstance(v, Variant) else v) for k, v in props.items()}

    def _absorb(self, path: str, interfaces: dict) -> None:
        if DEVICE_IFACE in interfaces:
            self._props.setdefault(path, {}).update(
                self._unwrap(interfaces[DEVICE_IFACE]))
        if path == self._adapter_path and ADAPTER_IFACE in interfaces:
            adapter = self._unwrap(interfaces[ADAPTER_IFACE])
            self._powered = bool(adapter.get("Powered", self._powered))
            self._scanning = bool(adapter.get("Discovering", self._scanning))

    def _on_signal(self, msg: Message):
        if msg.member == "InterfacesAdded":
            self._absorb(msg.body[0], msg.body[1])
        elif msg.member == "InterfacesRemoved":
            self._props.pop(msg.body[0], None)
        elif msg.member == "PropertiesChanged":
            self._absorb(msg.path, {msg.body[0]: msg.body[1]})
        else:
            return
        self._publish()

    # -- commands ------------------------------------------------------
    def _path(self, mac: str) -> str:
        return f"{self._adapter_path}/dev_{mac.replace(':', '_').upper()}"

    def _submit(self, coro):
        """Schedule a coroutine on the bus thread.

        Returns a concurrent Future, or None when the loop is already gone --
        in which case the coroutine is closed explicitly. Dropping it instead
        leaves an un-awaited coroutine for the garbage collector to complain
        about later, at a point in the log with nothing to do with the cause.
        """
        if self._loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self._loop)
        coro.close()
        return None

    def _start(self, op: str, mac: str, coro_factory) -> None:
        if self._busy:
            return
        self._busy = (op, mac, time.monotonic())
        self._publish()
        self._submit(self._guard(op, mac, coro_factory))

    async def _guard(self, op: str, mac: str, coro_factory) -> None:
        ok, error = True, ""
        try:
            self._task = asyncio.current_task()
            await coro_factory()
        except asyncio.CancelledError:
            self._busy = None            # cancel is silent: the app already spoke
            self._publish()
            return
        except Exception as exc:
            ok, error = False, _message(str(exc))
        finally:
            self._task = None
        self._seq += 1
        self._result = BtResult(self._seq, op, mac, ok, error)
        self._busy = None
        self._publish()

    async def _set_discovery(self, on: bool) -> None:
        member = "StartDiscovery" if on else "StopDiscovery"
        try:
            await self._call(self._adapter_path, ADAPTER_IFACE, member)
        except RuntimeError:
            pass                         # already started/stopped is not an error
        self._scanning = on
        self._publish()

    def scan(self, on: bool) -> None:
        self._submit(self._set_discovery(on))

    def pair(self, mac: str) -> None:
        """Pair, trust, connect: one intent, one result."""
        path = self._path(mac)

        async def run():
            try:
                await self._call(path, DEVICE_IFACE, "Pair")
            except RuntimeError as exc:
                if "AlreadyExists" not in str(exc):
                    raise
            await self._set_prop(path, DEVICE_IFACE, "Trusted", Variant("b", True))
            await self._call(path, DEVICE_IFACE, "Connect")
        self._start("pair", mac, lambda: run())

    def connect(self, mac: str) -> None:
        path = self._path(mac)

        async def run():
            try:
                await self._call(path, DEVICE_IFACE, "Connect")
            except RuntimeError as exc:
                if "AlreadyConnected" not in str(exc):
                    raise
        self._start("connect", mac, lambda: run())

    def disconnect(self, mac: str) -> None:
        self._start("disconnect", mac,
                    lambda: self._call(self._path(mac), DEVICE_IFACE, "Disconnect"))

    def forget(self, mac: str) -> None:
        self._start("forget", mac,
                    lambda: self._call(self._adapter_path, ADAPTER_IFACE,
                                       "RemoveDevice", "o", [self._path(mac)]))

    def cancel(self) -> None:
        task = self._task
        if task:
            self._loop.call_soon_threadsafe(task.cancel)
        self._busy = None
        self._publish()

    def close(self) -> None:
        """Stop discovery, then the bus thread — in that order, and waited on.

        Scheduling StopDiscovery and stopping the loop on the next line
        destroys the task mid-flight, so the adapter is *left discovering*
        after the app has gone. On a battery device that is a radio drain
        against the 8-hour target, and an active discovery on the shared
        2.4 GHz radio is a known cause of A2DP stutter — so the symptom
        reaching anyone would be "the speaker crackles sometimes".

        The waits are bounded: shutdown must not hang because BlueZ is wedged.
        """
        if self._scanning:
            pending = self._submit(self._set_discovery(False))
            if pending is not None:
                try:
                    pending.result(timeout=2.0)
                except Exception:        # noqa: BLE001 - we are closing anyway
                    pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)
