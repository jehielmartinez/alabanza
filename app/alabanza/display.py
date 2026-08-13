"""Display abstraction.

The app produces a ViewModel (what should be on screen); a Display renders
it. Phase 0 renders to the terminal with curses; Phase 1 adds a luma.oled
implementation drawing the same ViewModel on the real 128x64 OLED.

Layout (8 rows x 25 cols, the real OLED's text capacity):

    r0  status bar     "> Sonando        Jack V80"
    r1  separator
    r2  title          "005 - Al Cielo Voy"   (marquee if long)
    r3  subtitle       matched title / context
    r4  progress bar
    r5  times          "01:23             04:10"
    r6  meta           "Vel 105%      Himno: 21_"
    r7  hint / transient messages

Menu and search screens replace rows 2-6 with a list.
"""

import curses
import time
from dataclasses import dataclass, field
from typing import Protocol

WIDTH = 25  # chars that fit on the 128x64 OLED with a 5x8 font


@dataclass
class ViewModel:
    state: str = "idle"           # idle | playing | paused | alt (menus)
    status_left: str = ""
    status_right: str = ""        # text form (terminal); OLED prefers the fields below
    output: str = ""              # "jack" / "bluetooth" / "hdmi" -> drawn as an icon
    volume: int | None = None     # number next to the output icon
    title: str = ""
    subtitle: str = ""
    progress: float | None = None  # 0..1, renders the bar row
    time_pos: str = ""
    time_dur: str = ""
    meta_left: str = ""
    meta_right: str = ""
    lines: list[str] = field(default_factory=list)  # menu/search list rows
    hint: str = ""


class Display(Protocol):
    def render(self, vm: ViewModel) -> None: ...


def split_row(left: str, right: str, width: int = WIDTH) -> str:
    """Left + right aligned into one row, left side truncated with an ellipsis."""
    space = width - len(right) - (1 if right else 0)
    if len(left) > space:
        left = left[: max(0, space - 1)] + "…"
    return left.ljust(space) + (" " + right if right else "")


def progress_bar(fraction: float, width: int = WIDTH) -> str:
    cells = width - 2
    filled = round(max(0.0, min(1.0, fraction)) * cells)
    return "▕" + "█" * filled + "░" * (cells - filled) + "▏"


def marquee(text: str, width: int = WIDTH, chars_per_sec: float = 4.0) -> str:
    """Scroll text that doesn't fit; stationary when it does."""
    if len(text) <= width:
        return text
    loop = text + "  ·  "
    offset = int(time.monotonic() * chars_per_sec) % len(loop)
    return (loop + loop)[offset: offset + width]


class CursesDisplay:
    """Terminal stand-in for the OLED, sized like the real thing."""

    KEY_HELP = (
        "keys: 0-9 number | Enter/# play | * clear | Space pause | s stop | "
        "arrows seek/browse | -/+ speed | / search | m menu | r rescan | q quit"
    )
    _STATE_PAIR = {"playing": 1, "paused": 2, "alt": 3, "idle": 0}

    def __init__(self, screen: "curses.window"):
        self.screen = screen
        curses.curs_set(0)
        self.colors = curses.has_colors()
        if self.colors:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_CYAN, -1)

    def _color(self, state: str, extra: int = 0) -> int:
        pair = self._STATE_PAIR.get(state, 0)
        attr = curses.color_pair(pair) if (self.colors and pair) else 0
        return attr | extra

    def render(self, vm: ViewModel) -> None:
        s = self.screen
        s.erase()
        h, w = s.getmaxyx()
        rows = self._compose(vm)
        box_w = WIDTH + 4
        top, left = max(1, (h - 10) // 3), max(0, (w - box_w) // 2)

        frame = self._color(vm.state, curses.A_BOLD)
        s.addnstr(top - 1, left, "┌─ ALABANZA " + "─" * (box_w - 13) + "┐", box_w, frame)
        for i, (text, attr) in enumerate(rows):
            s.addnstr(top + i, left, "│", 1, frame)
            s.addnstr(top + i, left + 2, text[:WIDTH].ljust(WIDTH), WIDTH, attr)
            s.addnstr(top + i, left + box_w - 1, "│", 1, frame)
        s.addnstr(top + len(rows), left, "└" + "─" * (box_w - 2) + "┘", box_w, frame)

        if h > top + len(rows) + 2:
            s.addnstr(h - 1, 0, self.KEY_HELP[: w - 1], w - 1, curses.A_DIM)
        s.refresh()

    def _compose(self, vm: ViewModel) -> list[tuple[str, int]]:
        bold = curses.A_BOLD
        dim = curses.A_DIM
        accent = self._color(vm.state, bold)
        cyan = self._color("alt")

        rows: list[tuple[str, int]] = [
            (split_row(vm.status_left, vm.status_right), accent),
            ("─" * WIDTH, dim),
        ]
        if vm.lines:
            body = vm.lines[:5]
            for line in body:
                is_cursor = line.startswith("> ")
                rows.append((line, (accent if is_cursor else 0)))
            rows += [("", 0)] * (5 - len(body))
        else:
            rows.append((marquee(vm.title), accent))
            rows.append((vm.subtitle, cyan))
            rows.append((progress_bar(vm.progress) if vm.progress is not None else "", 0))
            rows.append((split_row(vm.time_pos, vm.time_dur), 0))
            rows.append((split_row(vm.meta_left, vm.meta_right), bold))
        rows.append((vm.hint, dim | curses.A_ITALIC))
        return rows
