"""Render every screen state to PNGs — see the exact OLED pixels
without owning the hardware.

    uv run python -m alabanza.preview [out_dir]
"""

import sys
from pathlib import Path

from PIL import Image

from .display import ViewModel
from .oled import render

SCALE = 4
BLUE = (80, 170, 255)  # the panel is blue-on-black

SCREENS = {
    "idle": ViewModel(
        state="idle", status_right="Jack V80", output="jack", volume=80,
        title="Himno: ---", subtitle="selecciona un número",
    ),
    "entry": ViewModel(
        state="idle", status_right="Jack V80", output="jack", volume=80,
        title="Himno: 279_", subtitle="¡Santo! ¡Santo! ¡Santo!",
    ),
    # paused is identical to playing except the status line — that's the
    # actual app behavior (pause freezes everything else in place)
    "playing": ViewModel(
        state="playing", status_left="▶ Sonando", status_right="BT V60", output="bluetooth", volume=60,
        title="279 · ¡Santo! ¡Santo! ¡Santo!",
        progress=0.62, time_pos="02:24", time_dur="03:51",
        meta_left="Vel 105%",
    ),
    "paused": ViewModel(
        state="paused", status_left="❚❚ Pausa", status_right="BT V60", output="bluetooth", volume=60,
        title="279 · ¡Santo! ¡Santo! ¡Santo!",
        progress=0.62, time_pos="02:24", time_dur="03:51",
        meta_left="Vel 105%",
    ),
    # a transient message temporarily replaces the bottom row
    "speed_flash": ViewModel(
        state="playing", status_left="▶ Sonando", status_right="BT V60", output="bluetooth", volume=60,
        title="279 · ¡Santo! ¡Santo! ¡Santo!",
        progress=0.62, time_pos="02:24", time_dur="03:51",
        meta_left="Vel 110%", hint="Velocidad: 110%",
    ),
    "search": ViewModel(
        state="alt", status_left="BUSCAR", status_right="10 res.",
        lines=["Buscar: 243_", "> 005 Al Cielo Voy", "  014 Bienvenida da Jesús",
               "  063 Jesús del Cielo"],
    ),
    # The first thing an operator sees on entering search, and the only place
    # that teaches predictive T9. It had no golden, so the hint could have
    # been clipped by the panel without any test noticing.
    "search_empty": ViewModel(
        state="alt", status_left="BUSCAR",
        lines=["Buscar: _", "  1 toque por letra", "  ej: Cielo = 24356"],
        hint="* borrar",
    ),
    "menu": ViewModel(
        state="alt", status_left="MENU",
        lines=["> Salida: Bluetooth", "  Bluetooth", "  Buscar por titulo"],
        hint="* volver",
    ),
    # ✓ connected · paired, no glyph = discovered but not paired
    "bt_list": ViewModel(
        state="alt", status_left="Bluetooth", status_right="buscando…",
        lines=["> ✓JBL Flip 5", "  ·Bocina Iglesia", "   Soundcore 2"],
        hint="gira y pulsa",
    ),
    "bt_scan": ViewModel(
        state="alt", status_left="Bluetooth", status_right="buscando…",
        lines=["  ·Bocina Iglesia", "   Soundcore 2", "> Buscar de nuevo"],
        hint="gira y pulsa",
    ),
    "bt_busy": ViewModel(
        state="alt", status_left="Bluetooth", status_right="4s",
        lines=["Conectando…", "  JBL Flip 5"], hint="*: cancelar",
    ),
    "bt_device": ViewModel(
        state="alt", status_left="JBL Flip 5", status_right="✓",
        lines=["> Desconectar", "  Olvidar", "  Volver"], hint="gira y pulsa",
    ),
    "bt_forget": ViewModel(
        state="alt", status_left="¿Olvidar?",
        lines=["  JBL Flip 5", "  Sí", "> No"],
        hint="gira y pulsa",
    ),
    # the speaker is gone: struck-through rune, "--" where the volume was
    "bt_lost": ViewModel(
        state="paused", status_left="❚❚ Pausa", output="bluetooth",
        output_state="down", volume=60,
        title="279 · ¡Santo! ¡Santo! ¡Santo!",
        progress=0.62, time_pos="02:24", time_dur="03:51",
        hint="BT perdido - pausado",
    ),
    # the Bible: pick a book (T9 narrowing the list), then a chapter and a
    # verse on the same screen; then the passage, with its first words so
    # the operator can check it without looking at the wall
    "bible_book": ViewModel(
        state="alt", status_left="BIBLIA",
        lines=["Libro: 58_", "> Juan", "  1 Juan", "  2 Juan"],
    ),
    "bible_chapter": ViewModel(
        state="alt", status_left="BIBLIA",
        lines=["  Juan", "> Capítulo 3", "  de 21"],
        hint="gira y pulsa",
    ),
    "bible_show": ViewModel(
        state="alt", status_left="BIBLIA", status_right="36 vers.",
        title="Juan 3:16-18",
        subtitle="Porque de tal manera amó Dios al mundo, que ha dado",
        hint="* quita · # añade",
    ),
    "bt_connecting": ViewModel(
        state="idle", output="bluetooth",
        output_state="connecting", volume=60,
        title="Himno: ---", subtitle="selecciona un número",
    ),
}


def to_png(vm: ViewModel, path: Path) -> None:
    mono = render(vm)
    rgb = Image.new("RGB", mono.size, (2, 4, 10))
    blue = Image.new("RGB", mono.size, BLUE)
    rgb.paste(blue, mask=mono)
    rgb = rgb.resize((mono.width * SCALE, mono.height * SCALE), Image.NEAREST)
    rgb.save(path)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("oled-preview")
    out.mkdir(parents=True, exist_ok=True)
    for name, vm in SCREENS.items():
        to_png(vm, out / f"{name}.png")
    print(f"{len(SCREENS)} screens rendered to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
