"""The Alabanza state machine — pure logic, no hardware.

Receives Events, drives the Player, and produces a ViewModel each tick.
Knows nothing about curses, GPIO, or OLEDs.
"""

import time
from enum import Enum, auto
from pathlib import Path

from .display import ViewModel
from .events import Event, Kind
from .library import Library, scan
from .player import SEEK_STEP_SECONDS, Player


class Mode(Enum):
    SELECT = auto()
    MENU = auto()
    SEARCH = auto()


MENU_ITEMS = ["Output: Jack (phase 2)", "Rescan library", "Quit"]


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


class App:
    def __init__(self, library_dir: Path, player: Player):
        self.library_dir = library_dir
        self.library: Library = scan(library_dir)
        self.player = player
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

    # -- helpers -------------------------------------------------------
    def flash(self, text: str, seconds: float = 2.5) -> None:
        self._message = text
        self._message_until = time.monotonic() + seconds

    @property
    def message(self) -> str:
        return self._message if time.monotonic() < self._message_until else ""

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
        self.player.play(hymn.path)
        self.now_playing = hymn
        self.browse = hymn.number
        self.entry = ""

    # -- event handling ------------------------------------------------
    def handle(self, event: Event) -> None:
        if event.kind is Kind.QUIT:
            self.quit_requested = True
        elif event.kind is Kind.RESCAN:
            self.library = scan(self.library_dir)
            self.flash(f"{len(self.library.hymns)} hymns indexed")
        elif self.mode is Mode.MENU:
            self._handle_menu(event)
        elif self.mode is Mode.SEARCH:
            self._handle_search(event)
        else:
            self._handle_select(event)

    def _handle_select(self, event: Event) -> None:
        k = event.kind
        if k is Kind.DIGIT:
            if len(self.entry) < 3:
                self.entry += str(event.value)
        elif k is Kind.STAR:
            self.entry = self.entry[:-1]
        elif k is Kind.CONFIRM:
            self._play_selected()
        elif k is Kind.PLAY_PAUSE:
            if self.player.active:
                self.player.toggle_pause()
            else:
                self._play_selected()
        elif k is Kind.STOP:
            self.player.stop()
            self.now_playing = None
        elif k is Kind.SEEK_BACK:
            self.player.seek(-SEEK_STEP_SECONDS)
        elif k is Kind.SEEK_FWD:
            self.player.seek(SEEK_STEP_SECONDS)
        elif k in (Kind.SPEED_DOWN, Kind.SPEED_UP):
            before = self.player.speed
            after = self.player.nudge_speed(+1 if k is Kind.SPEED_UP else -1)
            pct = round(after * 100)
            if after == before:
                self.flash(f"Vel {'max' if k is Kind.SPEED_UP else 'min'}: {pct}%", 1.5)
            else:
                self.flash(f"Velocidad: {pct}%", 1.5)
        elif k in (Kind.ENC_UP, Kind.ENC_DOWN):
            step = +1 if k is Kind.ENC_UP else -1
            if self.player.active:
                self.player.nudge_volume(step)  # spec: encoder = volume in playback
            else:
                self.entry = ""
                self.browse = self.library.neighbor(self.browse, step)
        elif k is Kind.ENC_PUSH:
            if not self.player.active:
                self._play_selected()
        elif k is Kind.MENU:
            self.mode = Mode.MENU
            self.menu_pos = 0
        elif k is Kind.SEARCH:
            self.mode = Mode.SEARCH
            self.search_query = ""
            self.search_pos = 0
            self.entry = ""

    def _handle_search(self, event: Event) -> None:
        k = event.kind
        if k in (Kind.MENU, Kind.SEARCH):
            self.mode = Mode.SELECT
        elif k is Kind.DIGIT:
            self.search_query += str(event.value)
            self.search_pos = 0
        elif k is Kind.STAR:
            if self.search_query:
                self.search_query = self.search_query[:-1]
                self.search_pos = 0
            else:
                self.mode = Mode.SELECT
        elif k in (Kind.ENC_UP, Kind.ENC_DOWN):
            results = self.library.search_t9(self.search_query)
            if results:
                step = +1 if k is Kind.ENC_UP else -1
                self.search_pos = (self.search_pos + step) % len(results)
        elif k in (Kind.CONFIRM, Kind.ENC_PUSH, Kind.PLAY_PAUSE):
            results = self.library.search_t9(self.search_query)
            if not results:
                self.flash("Sin resultados")
                return
            hymn = results[min(self.search_pos, len(results) - 1)]
            self.player.play(hymn.path)
            self.now_playing = hymn
            self.browse = hymn.number
            self.mode = Mode.SELECT

    def _handle_menu(self, event: Event) -> None:
        k = event.kind
        if k is Kind.MENU:
            self.mode = Mode.SELECT
        elif k in (Kind.ENC_UP, Kind.ENC_DOWN):
            step = +1 if k is Kind.ENC_UP else -1
            self.menu_pos = (self.menu_pos + step) % len(MENU_ITEMS)
        elif k in (Kind.CONFIRM, Kind.ENC_PUSH):
            item = MENU_ITEMS[self.menu_pos]
            if item == "Quit":
                self.quit_requested = True
            elif item == "Rescan library":
                self.handle(Event(Kind.RESCAN))
                self.mode = Mode.SELECT
            else:
                self.flash("Available in phase 2")

    # -- view ----------------------------------------------------------
    def tick(self) -> ViewModel:
        if self.now_playing and not self.player.active:
            self.now_playing = None  # hymn finished on its own

        if self.mode is Mode.SEARCH:
            return self._view_search()
        if self.mode is Mode.MENU:
            return self._view_menu()
        return self._view_select()

    def _view_search(self) -> ViewModel:
        results = self.library.search_t9(self.search_query)
        lines = [f"Buscar: {self.search_query}_"]
        if not self.search_query:
            lines.append("  2-9 = letras (T9)")
        elif not results:
            lines.append("  (sin resultados)")
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
            hint=self.message or "*borrar  m:salir  ⏎:play",
        )

    def _view_menu(self) -> ViewModel:
        lines = [
            ("> " if i == self.menu_pos else "  ") + item
            for i, item in enumerate(MENU_ITEMS)
        ]
        return ViewModel(
            state="alt", status_left="MENU", lines=lines,
            hint=self.message or "m: volver",
        )

    def _view_select(self) -> ViewModel:
        p = self.player
        vm = ViewModel()
        vm.status_right = f"Jack V{p.volume:02d}"
        entry_label = f"Himno: {self.entry}_" if self.entry else ""
        entry_match = self.library.get(int(self.entry)) if self.entry else None

        if self.now_playing:
            vm.state = "paused" if p.paused else "playing"
            vm.status_left = "❚❚ Pausa" if p.paused else "▶ Sonando"
            vm.title = f"{self.now_playing.number:03d} · {self.now_playing.title}"
            vm.subtitle = entry_match.title if entry_match else ""
            vm.progress = (p.position / p.duration) if p.duration else 0.0
            vm.time_pos = _fmt_time(p.position)
            vm.time_dur = _fmt_time(p.duration)
            vm.meta_left = f"Vel {round(p.speed * 100)}%"
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
                vm.subtitle = "teclea un numero"
            n = len(self.library.hymns)
            vm.meta_left = f"{n} himnos" if n else "biblioteca vacia"

        vm.hint = self.message
        return vm
