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
        state="idle", status_left="● Listo", status_right="Jack V80", output="jack", volume=80,
        title="Himno: ---", subtitle="teclea un numero",
    ),
    "entry": ViewModel(
        state="idle", status_left="● Listo", status_right="Jack V80", output="jack", volume=80,
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
    "menu": ViewModel(
        state="alt", status_left="MENU",
        lines=["> Salida: Bluetooth", "  Bluetooth", "  Reescanear biblioteca",
               "  Salir"],
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
