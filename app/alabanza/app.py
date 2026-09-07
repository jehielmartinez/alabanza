"""The Alabanza state machine — pure logic, no hardware.

Receives Events, drives the Player, and produces a ViewModel each tick.
Knows nothing about curses, GPIO, OLEDs — or D-Bus: Bluetooth arrives as an
immutable snapshot polled each tick, so nothing here can block. Retry policy
lives here (it is policy); the backend is only mechanism. See docs/BLUETOOTH.md.
"""

import time
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path

from . import audio
from . import settings as settings_mod
from .bluetooth import (
    ERR_CONNECT,
    ERR_OFF,
    ERR_TIMEOUT,
    OP_LABELS,
    RECONNECT_DELAYS,
    SCAN_SECONDS,
    TIMEOUTS,
    BluetoothBackend,
    BtResult,
    BtState,
    NullBackend,
    visible,
)
from .display import ViewModel
from .events import Event, Kind
from .library import Library, scan
from .player import SEEK_STEP_SECONDS, Player
from .settings import OUTPUT_LABELS, Settings


class Mode(Enum):
    SELECT = auto()
    MENU = auto()
    SEARCH = auto()
    BT_LIST = auto()
    BT_DEVICE = auto()


SAVE_DEBOUNCE_S = 2.0
LIST_ROWS = 4          # what the real OLED fits
HINT_ROWS = 3          # ...minus one on any screen that shows a hint, because
                       # the hint is drawn over the fourth row
MSG_CHARS = 21         # what one flash message fits at 128 px


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _fit(text: str, width: int = MSG_CHARS) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _step(kind: Kind) -> int:
    """List movement, from either the D-pad or the wheel.

    Both do the obvious thing — ▲ moves up, clockwise scrolls down — and
    neither is ever advertised, because both are obvious. Returns 0 for
    anything that is not a movement.
    """
    if kind in (Kind.DOWN, Kind.WHEEL_CW):
        return +1
    if kind in (Kind.UP, Kind.WHEEL_CCW):
        return -1
    return 0


def _window(count: int, cursor: int, size: int = LIST_ROWS) -> int:
    """First visible row, so the cursor is always on screen."""
    return max(0, min(cursor - size + 1, count - size))


@dataclass
class _Reconnect:
    """A pending reconnect sequence: boot, loss recovery, or a Play retry."""

    mac: str = ""
    at: float = 0.0        # monotonic time of the next attempt
    step: int = 0          # index into RECONNECT_DELAYS
    left: int = 0          # attempts remaining
    quiet: bool = False    # Play retry: the warning has already been shown

    @property
    def active(self) -> bool:
        return bool(self.mac) and self.left > 0


class App:
    def __init__(self, library_dir: Path, player: Player,
                 settings_path: Path | None = None,
                 bt: BluetoothBackend | None = None,
                 clock=time.monotonic):
        # every deadline in here — message timeouts, the save debounce, scan
        # and reconnect timers — reads this one clock, so tests can drive
        # half-hour scenarios instantly instead of sleeping through them
        self._now = clock
        self.library_dir = library_dir
        self.library: Library = scan(library_dir)
        self.player = player
        self.settings_path = settings_path
        self.settings = settings_mod.load(settings_path) if settings_path else Settings()
        self.player.volume = self.settings.volume
        self.mode = Mode.SELECT
        self.entry = ""            # digits typed so far
        self.browse = 0            # hymn number the encoder is resting on
        self.menu_pos = 0
        self.search_query = ""
        self.search_pos = 0
        self.now_playing = None    # Hymn | None
        self.quit_requested = False
        self._message = ""
        self._message_until = 0.0
        self._dirty = False
        self._last_change = 0.0

        self.bt = bt or NullBackend()
        self.bt_cursor = 0         # row in the device list
        self.bt_mac = ""           # device open in BT_DEVICE
        self.bt_pos = 0            # row in the device action list
        self.bt_forget = False     # forget confirmation showing
        self.bt_forget_yes = False
        self._bt: BtState = self.bt.state()
        self._bt_seq = self._bt.last_result.seq if self._bt.last_result else 0
        self._scan_until = 0.0
        self._reconnect = _Reconnect()
        self._paused_by_loss = False
        self._apply_output()
        # decision 9: chase the last speaker at boot only when BT is the output
        if self.settings.output == "bluetooth" and self.settings.last_bt_device:
            self._start_reconnect(self.settings.last_bt_device)

    def _touch(self) -> None:
        """Mark settings changed; saved debounced in tick()."""
        self._dirty = True
        self._last_change = self._now()

    def _save_if_due(self, force: bool = False) -> None:
        if not (self._dirty and self.settings_path):
            return
        if force or self._now() - self._last_change > SAVE_DEBOUNCE_S:
            settings_mod.save(self.settings, self.settings_path)
            self._dirty = False

    # -- helpers -------------------------------------------------------
    def flash(self, text: str, seconds: float = 2.5) -> None:
        self._message = text
        self._message_until = self._now() + seconds

    @property
    def message(self) -> str:
        return self._message if self._now() < self._message_until else ""

    def _selected_number(self) -> int | None:
        if self.entry:
            return int(self.entry)
        if self.browse:
            return self.browse
        return None

    def _play_selected(self) -> None:
        number = self._selected_number()
        if number is None:
            self.flash("Type a hymn number")
            return
        hymn = self.library.get(number)
        if hymn is None:
            self.flash(f"No hymn {number}")
            return
        if self.settings.output == "bluetooth" and not self._bt.connected_mac:
            # spec: warn instead of playing into the void — and retry once, so
            # the operator's instinctive second press is the one that works
            self.flash("BT: no conectado", 4)
            self._start_reconnect(self.settings.last_bt_device, attempts=1, quiet=True)
            return
        if self._bt.scanning:
            self.bt.scan(False)     # discovery audibly degrades A2DP
        self.player.play(hymn.path)
        self.now_playing = hymn
        self.browse = hymn.number
        self.entry = ""

    # -- event handling ------------------------------------------------
    def handle(self, event: Event) -> None:
        if event.kind is Kind.QUIT:
            self._save_if_due(force=True)
            self.quit_requested = True
        elif event.kind is Kind.RESCAN:
            self.library = scan(self.library_dir)
            self.flash(f"{len(self.library.hymns)} hymns indexed")
        elif self.mode is Mode.MENU:
            if not self._handle_transport(event):
                self._handle_menu(event)
        elif self.mode is Mode.SEARCH:
            self._handle_search(event)
        elif self.mode is Mode.BT_LIST:
            if not self._handle_transport(event):
                self._handle_bt_list(event)
        elif self.mode is Mode.BT_DEVICE:
            if not self._handle_transport(event):
                self._handle_bt_device(event)
        else:
            self._handle_select(event)

    def _handle_transport(self, event: Event) -> bool:
        """Controls that work on every screen — a menu never hijacks the
        D-pad's play and seek. Returns True when the event was consumed.

        ▲ ▼ are deliberately *not* here: on a list screen they move the cursor.
        """
        k = event.kind
        if k is Kind.PLAY_PAUSE and self.player.active:
            self.player.toggle_pause()
        elif k is Kind.SEEK_BACK:
            self.player.seek(-SEEK_STEP_SECONDS)
        elif k is Kind.SEEK_FWD:
            self.player.seek(SEEK_STEP_SECONDS)
        else:
            return False
        return True

    def _nudge_speed(self, direction: int) -> None:
        before = self.player.speed
        after = self.player.nudge_speed(direction)
        pct = round(after * 100)
        if after == before:
            self.flash(f"Vel {'max' if direction > 0 else 'min'}: {pct}%", 1.5)
        else:
            self.flash(f"Velocidad: {pct}%", 1.5)

    def _handle_select(self, event: Event) -> None:
        k = event.kind
        if k is Kind.DIGIT:
            if len(self.entry) < 3:
                self.entry += str(event.value)
        elif k is Kind.STAR:
            # one key, one idea — "clear what is going on": erase the digit you
            # typed, or if there is nothing to erase, stop the hymn
            if self.entry:
                self.entry = self.entry[:-1]
            elif self.player.active:
                self.player.stop()
                self.now_playing = None
            else:
                # Nothing typed and nothing playing: clear the hymn still
                # named on screen. Without this the last hymn played stays
                # on the panel and * appears to do nothing, because the
                # number shown comes from `browse` rather than from `entry`.
                self.browse = 0
        elif k is Kind.CONFIRM:
            self._play_selected()
        elif k is Kind.PLAY_PAUSE:
            if self.player.active:
                self.player.toggle_pause()
            else:
                self._play_selected()
        elif k is Kind.SEEK_BACK:
            self.player.seek(-SEEK_STEP_SECONDS)
        elif k is Kind.SEEK_FWD:
            self.player.seek(SEEK_STEP_SECONDS)
        elif k in (Kind.UP, Kind.DOWN):
            # ▲ ▼ mean "adjust the thing in front of you": the speed of the
            # hymn that is playing, or which hymn you are looking at
            if self.player.active:
                self._nudge_speed(+1 if k is Kind.UP else -1)
            else:
                self.entry = ""
                self.browse = self.library.neighbor(
                    self.browse, +1 if k is Kind.DOWN else -1)
        elif k in (Kind.WHEEL_CW, Kind.WHEEL_CCW):
            # decision 6: the wheel is the volume, always — one meaning, so it
            # can be turned without looking
            self.settings.volume = self.player.nudge_volume(
                +1 if k is Kind.WHEEL_CW else -1)
            self._touch()
        elif k is Kind.PUSH:
            self.mode = Mode.MENU
            self.menu_pos = 0

    def _handle_search(self, event: Event) -> None:
        k = event.kind
        step = _step(k)
        if k is Kind.DIGIT:
            self.search_query += str(event.value)
            self.search_pos = 0
        elif k is Kind.STAR:
            if self.search_query:
                self.search_query = self.search_query[:-1]
                self.search_pos = 0
            else:
                self.mode = Mode.SELECT
        elif step:
            results = self.library.search_t9(self.search_query)
            if results:
                self.search_pos = (self.search_pos + step) % len(results)
        elif k in (Kind.CONFIRM, Kind.PUSH, Kind.PLAY_PAUSE):
            results = self.library.search_t9(self.search_query)
            if not results:
                self.flash("Sin resultados")
                return
            hymn = results[min(self.search_pos, len(results) - 1)]
            self.mode = Mode.SELECT
            self.entry = ""
            self.browse = hymn.number
            self._play_selected()

    def _menu_items(self) -> list[str]:
        return [
            f"Salida: {OUTPUT_LABELS[self.settings.output]}",
            "Bluetooth",
            "Buscar por titulo",
            "Reescanear biblioteca",
            "Salir",
        ]

    def _handle_menu(self, event: Event) -> None:
        k = event.kind
        step = _step(k)
        if k is Kind.STAR:
            self.mode = Mode.SELECT
        elif step:
            self.menu_pos = (self.menu_pos + step) % len(self._menu_items())
        elif k in (Kind.CONFIRM, Kind.PUSH):
            if self.menu_pos == 0:      # cycle audio output
                output = self.settings.next_output()
                self.player.volume = self.settings.volume  # per-output memory
                self._apply_output()
                self._touch()
                self.flash(f"Salida: {OUTPUT_LABELS[output]}  V{self.settings.volume}")
                if output == "bluetooth" and not self._bt.connected_mac:
                    # the next question is always "which speaker?"
                    self._open_bt_list()
            elif self.menu_pos == 1:    # bluetooth
                self._open_bt_list()
            elif self.menu_pos == 2:    # T9 title search (no letter keys)
                self.mode = Mode.SEARCH
                self.search_query = ""
                self.search_pos = 0
                self.entry = ""
            elif self.menu_pos == 3:    # rescan
                self.handle(Event(Kind.RESCAN))
                self.mode = Mode.SELECT
            else:                       # quit
                self._save_if_due(force=True)
                self.quit_requested = True

    # -- bluetooth -----------------------------------------------------
    def _bt_name(self, mac: str) -> str:
        device = self._bt.device(mac)
        return device.name if device else self.settings.bt_names.get(mac, mac)

    def _open_bt_list(self) -> None:
        self.mode = Mode.BT_LIST
        self.bt_cursor = 0
        if not self._bt.available:
            self.flash(ERR_OFF)
        elif not self._bt.connected_mac and not self.player.active:
            # nothing connected means the operator came here to fix that, so
            # start looking straight away — one less thing to press
            self._start_scan()

    def _start_scan(self) -> None:
        if not self._bt.available:
            self.flash(ERR_OFF)
        elif self.player.active:
            self.flash("Detén el himno", 3)   # discovery breaks up A2DP
        else:
            self.bt.scan(True)
            self._scan_until = self._now() + SCAN_SECONDS

    def _apply_output(self) -> None:
        """Point mpv at the sink for the selected output. Called when the
        output changes and when a speaker connects — the Bluetooth sink only
        exists once BlueZ has the link up."""
        try:
            self.player.audio_device = audio.resolve(
                self.player.audio_devices, self.settings.output,
                self._bt.connected_mac)
        except Exception:                # a bad sink name must never take the app down
            self.flash("Salida no disponible", 4)

    def _cancel_op(self) -> None:
        """Abandon the running operation. The cached snapshot is corrected in
        the same breath: it is a tick old, and a stale `busy_op` would swallow
        the very next command the operator gives."""
        self.bt.cancel()
        self._bt = replace(self._bt, busy_op="", busy_mac="")

    def _start_reconnect(self, mac: str, attempts: int = len(RECONNECT_DELAYS),
                         quiet: bool = False) -> None:
        if not mac or self._bt.busy_op:
            return
        self._reconnect = _Reconnect(mac=mac, at=self._now(), step=0,
                                     left=attempts, quiet=quiet)

    def _handle_bt_list(self, event: Event) -> None:
        k = event.kind
        devices = visible(self._bt.devices)
        if self._bt.busy_op and k is Kind.STAR:
            self._cancel_op()
            self.flash("Cancelado")
            return
        if k is Kind.STAR:
            self.bt.scan(False)
            self.mode = Mode.MENU
        elif _step(k):
            self.bt_cursor = (self.bt_cursor + _step(k)) % (len(devices) + 1)
        elif k in (Kind.CONFIRM, Kind.PUSH):
            if self._bt.busy_op:
                return
            if self.bt_cursor >= len(devices):     # the "Buscar de nuevo" row
                self._start_scan()
                return
            device = devices[self.bt_cursor]
            if device.paired:
                self.mode = Mode.BT_DEVICE
                self.bt_mac = device.mac
                self.bt_pos = 0
                self.bt_forget = False
            else:
                # "use this speaker" is one intent: pair chains into connect
                self.bt.scan(False)
                self.bt.pair(device.mac)

    def _bt_actions(self) -> list[str]:
        device = self._bt.device(self.bt_mac)
        connected = bool(device and device.connected)
        return ["Desconectar" if connected else "Conectar", "Olvidar", "Volver"]

    def _handle_bt_device(self, event: Event) -> None:
        k = event.kind
        if self._bt.busy_op and k is Kind.STAR:
            self._cancel_op()
            self.flash("Cancelado")
            return
        if self.bt_forget:
            if _step(k):
                self.bt_forget_yes = not self.bt_forget_yes
            elif k is Kind.STAR:
                self.bt_forget = False
            elif k in (Kind.CONFIRM, Kind.PUSH):
                self.bt_forget = False
                if self.bt_forget_yes:
                    self.bt.forget(self.bt_mac)
                    self.mode = Mode.BT_LIST
            return

        if k is Kind.STAR:
            self.mode = Mode.BT_LIST
        elif _step(k):
            self.bt_pos = (self.bt_pos + _step(k)) % len(self._bt_actions())
        elif k in (Kind.CONFIRM, Kind.PUSH):
            if self._bt.busy_op:
                return
            device = self._bt.device(self.bt_mac)
            if self.bt_pos == 0:
                if device and device.connected:
                    self.bt.disconnect(self.bt_mac)
                else:
                    self._reconnect = _Reconnect()   # an explicit press wins
                    self.bt.connect(self.bt_mac)
                self.mode = Mode.BT_LIST
            elif self.bt_pos == 1:
                self.bt_forget = True
                self.bt_forget_yes = False           # default to No
            else:
                self.mode = Mode.BT_LIST

    def _bt_poll(self) -> None:
        """Diff the snapshot against last tick: results, losses, timeouts."""
        now = self._now()
        prev, cur = self._bt, self.bt.state()
        self._bt = cur

        result = cur.last_result
        if result and result.seq != self._bt_seq:
            self._bt_seq = result.seq
            self._on_bt_result(result, now)

        if cur.busy_op and now - cur.busy_since > TIMEOUTS.get(cur.busy_op, 15.0):
            self._cancel_op()
            self._on_op_failed(cur.busy_op, cur.busy_mac, now, ERR_TIMEOUT)

        if cur.scanning and now > self._scan_until:
            self.bt.scan(False)

        # the speaker went away on its own (an intentional disconnect is the
        # op that just finished, and must not raise an alarm)
        lost = prev.connected_mac and not cur.connected_mac
        user_asked = prev.busy_op in ("disconnect", "forget")
        if lost and not user_asked and self.settings.output == "bluetooth":
            if self.player.active and not self.player.paused:
                self.player.toggle_pause()
                self._paused_by_loss = True
                self.flash("BT perdido - pausado", 6)
            else:
                self.flash("BT perdido", 4)
            self._start_reconnect(prev.connected_mac)

        if self._paused_by_loss and not (self.player.active and self.player.paused):
            self._paused_by_loss = False

        if self._reconnect.active and not cur.busy_op and now >= self._reconnect.at:
            if cur.connected_mac == self._reconnect.mac:
                self._reconnect = _Reconnect()
            else:
                self._reconnect.left -= 1
                self.bt.connect(self._reconnect.mac)

    def _on_bt_result(self, result: BtResult, now: float) -> None:
        name = _fit(self._bt_name(result.mac), MSG_CHARS - 11)
        if result.op in ("pair", "connect"):
            if result.ok:
                reconnected = self._reconnect.mac == result.mac
                self._reconnect = _Reconnect()
                self.settings.last_bt_device = result.mac
                self.settings.bt_names[result.mac] = self._bt_name(result.mac)
                self._apply_output()
                self._touch()
                if self._paused_by_loss:
                    # the hymn is still paused and the operator needs to know
                    # that pressing Play is what happens next
                    self.flash("Reconectado - Play", 6)
                else:
                    self.flash("BT reconectado" if reconnected
                               else f"Conectado: {name}")
            else:
                self._on_op_failed(result.op, result.mac, now,
                                   result.error or ERR_CONNECT)
        elif not result.ok:
            self._on_op_failed(result.op, result.mac, now,
                               result.error or ERR_CONNECT)
        elif result.op == "disconnect":
            self.flash("Desconectado")
        elif result.op == "forget":
            self.settings.bt_names.pop(result.mac, None)
            if self.settings.last_bt_device == result.mac:
                self.settings.last_bt_device = ""
            self._touch()
            self.flash("Olvidado")

    def _on_op_failed(self, op: str, mac: str, now: float, message: str) -> None:
        """Schedule the next reconnect attempt, or report the failure once.

        A retry sequence stays silent until it gives up: three identical
        `Sin respuesta` flashes tell the operator nothing the last one won't.
        """
        pending = self._reconnect
        retrying = pending.mac == mac and op in ("pair", "connect")
        if retrying and pending.left > 0:
            pending.step = min(pending.step + 1, len(RECONNECT_DELAYS) - 1)
            pending.at = now + RECONNECT_DELAYS[pending.step]
            return
        if retrying:
            self._reconnect = _Reconnect()
            if pending.quiet:
                return               # the Play warning already said this
            message = "BT: no conectado"
        self.flash(message, 4)

    def _output_state(self) -> str:
        """How the status bar should draw the output icon."""
        if self.settings.output != "bluetooth":
            return "ok"
        if self._bt.connected_mac:
            return "ok"
        if self._bt.busy_op in ("connect", "pair") or self._reconnect.active:
            return "connecting"
        return "down"

    # -- view ----------------------------------------------------------
    def tick(self) -> ViewModel:
        self._bt_poll()
        self._save_if_due()
        if self.now_playing and not self.player.active:
            self.now_playing = None       # hymn finished on its own
            self.browse = 0               # ...panel back to "teclea un numero"
            self.player.show_idle()       # ...and HDMI back to the image

        if self.mode is Mode.SEARCH:
            return self._view_search()
        if self.mode is Mode.MENU:
            return self._view_menu()
        if self.mode is Mode.BT_LIST:
            return self._view_bt_busy() or self._view_bt_list()
        if self.mode is Mode.BT_DEVICE:
            return self._view_bt_busy() or self._view_bt_device()
        return self._view_select()

    def _view_search(self) -> ViewModel:
        results = self.library.search_t9(self.search_query)
        lines = [f"Buscar: {self.search_query}_"]
        if not self.search_query:
            # An example rather than a rule. This is predictive T9, not
            # multi-tap, and nothing on the panel said so — the operator's
            # instinct from a phone is to press 2 three times for "c", which
            # searches for a different thing entirely and finds nothing.
            lines += ["  1 toque por letra", "  ej: Cielo = 24356"]
        elif not results:
            lines += ["  (sin resultados)", "  1 toque por letra"]
        else:
            pos = min(self.search_pos, len(results) - 1)
            lines += [
                ("> " if h is results[pos] else "  ") + f"{h.number:03d} {h.title}"
                for h in results[pos: pos + 4]
            ]
        return ViewModel(
            state="alt",
            status_left="BUSCAR",
            status_right=f"{len(results)} res." if self.search_query else "",
            lines=lines,
            hint=self.message or "* borrar",
        )

    def _view_menu(self) -> ViewModel:
        items = self._menu_items()
        start = _window(len(items), self.menu_pos, HINT_ROWS)
        lines = [
            ("> " if i == self.menu_pos else "  ") + item
            for i, item in enumerate(items[start: start + HINT_ROWS], start)
        ]
        return ViewModel(
            state="alt", status_left="MENU", lines=lines,
            hint=self.message or "* volver",
        )

    def _view_bt_busy(self) -> ViewModel | None:
        """An operation in flight replaces the list body — same mode, and the
        operator can still walk away: the op keeps running."""
        st = self._bt
        if not st.busy_op:
            return None
        elapsed = int(max(0.0, self._now() - st.busy_since))
        return ViewModel(
            state="alt", status_left="Bluetooth", status_right=f"{elapsed}s",
            lines=[f"{OP_LABELS.get(st.busy_op, '')}…",
                   "  " + _fit(self._bt_name(st.busy_mac))],
            hint=self.message or "* cancelar",
        )

    def _view_bt_list(self) -> ViewModel:
        st = self._bt
        devices = visible(st.devices)
        # the last row is an action, so the whole screen is encoder-only:
        # turn to choose a speaker or "search again", push to act
        rows = [("✓" if d.connected else ("·" if d.paired else " ")) + d.name
                for d in devices]
        rows.append("Buscar de nuevo")   # the status bar already says "buscando…"
        cursor = min(self.bt_cursor, len(rows) - 1)
        start = _window(len(rows), cursor, HINT_ROWS)

        lines = [("> " if i == cursor else "  ") + row
                 for i, row in enumerate(rows[start: start + HINT_ROWS], start)]

        if not st.available:
            lines, right = ["  " + ERR_OFF], ""
        elif st.scanning:
            right = "buscando…"
        else:
            right = f"{len(devices)} disp." if devices else ""
        return ViewModel(
            state="alt", status_left="Bluetooth", status_right=right, lines=lines,
            hint=self.message or "gira y pulsa",
        )

    def _view_bt_device(self) -> ViewModel:
        device = self._bt.device(self.bt_mac)
        name = _fit(self._bt_name(self.bt_mac))
        if self.bt_forget:
            # the question goes in the status bar: three rows is all the hint
            # row leaves, and the cursor must be one of them
            return ViewModel(
                state="alt", status_left="¿Olvidar?",
                lines=["  " + name,
                       ("> " if self.bt_forget_yes else "  ") + "Sí",
                       ("  " if self.bt_forget_yes else "> ") + "No"],
                hint=self.message or "gira y pulsa",
            )
        lines = [("> " if i == self.bt_pos else "  ") + action
                 for i, action in enumerate(self._bt_actions())]
        return ViewModel(
            state="alt", status_left=name,
            status_right="✓" if device and device.connected else "",
            lines=lines, hint=self.message or "gira y pulsa",
        )

    def _view_select(self) -> ViewModel:
        p = self.player
        vm = ViewModel()
        vm.status_right = f"{OUTPUT_LABELS[self.settings.output]} V{p.volume:02d}"
        vm.output = self.settings.output
        vm.output_state = self._output_state()
        vm.volume = p.volume
        if vm.output_state == "down":
            vm.status_right = f"{OUTPUT_LABELS[self.settings.output]} --"
        elif vm.output_state == "connecting":
            vm.status_right = f"{OUTPUT_LABELS[self.settings.output]} …"
        entry_label = f"Himno: {self.entry}_" if self.entry else ""
        entry_match = self.library.get(int(self.entry)) if self.entry else None

        if self.now_playing:
            # One snapshot, then build the frame from it. Every attribute here
            # is a live call into mpv, and the hymn can end between two of
            # them: reading duration twice in the progress expression -- once
            # to guard against zero, once to divide by -- crashed the app when
            # a hymn ended in that gap. Snapshotting also stops a single frame
            # showing a position and a duration measured moments apart.
            paused = p.paused
            position, duration, speed = p.position, p.duration, p.speed
            vm.state = "paused" if paused else "playing"
            vm.status_left = "❚❚ Pausa" if paused else "▶ Sonando"
            vm.title = f"{self.now_playing.number:03d} · {self.now_playing.title}"
            vm.subtitle = entry_match.title if entry_match else ""
            vm.progress = (position / duration) if duration else 0.0
            vm.time_pos = _fmt_time(position)
            vm.time_dur = _fmt_time(duration)
            vm.meta_left = f"Vel {round(speed * 100)}%"
            vm.meta_right = entry_label
        else:
            vm.state = "idle"
            vm.status_left = "● Listo"
            if self.entry:
                vm.title = entry_label
                vm.subtitle = entry_match.title if entry_match else "?"
            elif self.browse:
                hymn = self.library.get(self.browse)
                vm.title = f"Himno: {self.browse:03d}"
                vm.subtitle = hymn.title if hymn else ""
            else:
                vm.title = "Himno: ---"
                vm.subtitle = ("teclea un numero" if self.library.hymns
                               else "biblioteca vacia")

        vm.hint = self.message
        return vm
