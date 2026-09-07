"""OLED rendering: ViewModel -> 128x64 1-bit image -> SSD1309.

Pure Pillow, so it runs anywhere (previews on a dev machine, the real
display on the device). Only OledDisplay touches luma.oled, lazily.

Fonts: Terminus (vendored in fonts/, OFL license) — a pixel font with
full Spanish coverage, crisp at exact sizes 12/16 on a 1-bit panel.

Layout (128x64):
    y0   status bar (drawn icon + text | right text)
    y13  separator
    y16  lists: 4 rows of 12px, cursor row inverted
      or title (16px bold, pixel marquee)
    y34  subtitle (idle) / progress bar (playing)
    y42+ bottom row: times + speed (playing) or meta (idle);
         transient hints replace it
"""

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .display import ViewModel

WIDTH, HEIGHT = 128, 64
_FONTS = Path(__file__).parent / "fonts"
# Layout.BASIC is pinned, not defaulted to. Pillow picks Raqm (HarfBuzz
# shaping, with kerning) whenever libraqm is present and BASIC when it is
# not — so the same Pillow and the same freetype render this panel two
# different ways depending on the machine. Raqm is present on Raspberry Pi OS
# and absent on macOS, which means the device was drawing text measurably
# tighter than the design it was tuned against. Terminus is a pixel font with
# fixed advances; shaping it is wrong here as well as non-deterministic.
_LAYOUT = ImageFont.Layout.BASIC
FONT_SMALL = ImageFont.truetype(str(_FONTS / "TerminusTTF-4.49.3.ttf"), 12,
                                layout_engine=_LAYOUT)
FONT_TITLE = ImageFont.truetype(str(_FONTS / "TerminusTTF-Bold-4.49.3.ttf"), 14,
                                layout_engine=_LAYOUT)


def _w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _fit(draw, text: str, font, width: int = WIDTH) -> str:
    """Trim to the panel with an ellipsis. Hymn titles are long — "Bienvenida
    da Jesús" is wider than 128 px — and silently running off the glass looks
    like a rendering fault rather than a long title."""
    if _w(draw, text, font) <= width:
        return text
    while text and _w(draw, text + "…", font) > width:
        text = text[:-1]
    return text + "…"


def _draw_status_icon(draw, icon: str) -> None:
    if icon == "▶":
        draw.polygon([(1, 2), (1, 10), (9, 6)], fill=1)
    elif icon == "❚❚":
        draw.rectangle((1, 2, 3, 10), fill=1)
        draw.rectangle((6, 2, 8, 10), fill=1)
    elif icon == "●":
        draw.ellipse((1, 3, 8, 10), fill=1)


def _draw_headphones(draw, x: int, y: int) -> None:
    """Jack output: headband arc + two earpads."""
    draw.arc((x, y, x + 9, y + 9), 180, 360, fill=1)
    draw.arc((x, y + 1, x + 9, y + 10), 180, 360, fill=1)
    draw.rectangle((x, y + 5, x + 2, y + 9), fill=1)
    draw.rectangle((x + 7, y + 5, x + 9, y + 9), fill=1)


def _draw_bt_rune(draw, x: int, y: int) -> None:
    """Bluetooth output: the angular 'B' rune."""
    m = x + 4                                   # the vertical stem
    draw.line((m, y, m, y + 10), fill=1)
    draw.line((m, y, m + 4, y + 3), fill=1)     # top-right diagonal
    draw.line((m + 4, y + 3, m - 4, y + 8), fill=1)
    draw.line((m - 4, y + 3, m + 4, y + 8), fill=1)
    draw.line((m + 4, y + 8, m, y + 10), fill=1)


def _draw_monitor(draw, x: int, y: int) -> None:
    """HDMI output: a screen on a stand."""
    draw.rectangle((x, y + 1, x + 9, y + 7), outline=1, fill=0)
    draw.line((x + 4, y + 8, x + 5, y + 8), fill=1)
    draw.line((x + 2, y + 9, x + 7, y + 9), fill=1)


def _strike(draw, x: int, y: int) -> None:
    """Slash an output icon: the selected output isn't there.

    A black channel is cleared first so the slash reads as a slash and not as
    one more stroke of the rune. No blinking — a flashing status bar in a dim
    sanctuary reads as a fault.
    """
    draw.line((x - 1, y + 11, x + 10, y), fill=0, width=3)
    draw.line((x - 1, y + 11, x + 10, y), fill=1)


_OUTPUT_ICONS = {
    "jack": _draw_headphones,
    "bluetooth": _draw_bt_rune,
    "hdmi": _draw_monitor,
}


def _status_bar(draw, vm: ViewModel) -> None:
    left = vm.status_left
    x = 0
    for icon in ("▶", "❚❚", "●"):
        if left.startswith(icon):
            _draw_status_icon(draw, icon)
            left = left.removeprefix(icon).lstrip()
            x = 13
            break
    draw.text((x, 0), left, font=FONT_SMALL, fill=1)

    if vm.volume is not None and vm.output in _OUTPUT_ICONS:
        # "<icon>80" right-aligned; the number says whether the output is there
        vol = {"down": "--", "connecting": "…"}.get(vm.output_state, str(vm.volume))
        right = WIDTH - _w(draw, vol, FONT_SMALL)
        draw.text((right, 0), vol, font=FONT_SMALL, fill=1)
        _OUTPUT_ICONS[vm.output](draw, right - 13, 0)
        if vm.output_state == "down":
            _strike(draw, right - 13, 0)
    elif vm.status_right:
        draw.text((WIDTH - _w(draw, vm.status_right, FONT_SMALL), 0),
                  vm.status_right, font=FONT_SMALL, fill=1)
    draw.line((0, 13, WIDTH, 13), fill=1)


def _marquee_px(draw, y, text, font, px_per_sec=24, now=None):
    """Draw text at y; pixel-scroll it when wider than the screen."""
    if _w(draw, text, font) <= WIDTH:
        draw.text((0, y), text, font=font, fill=1)
        return
    loop = text + "  ·  "
    loop_w = _w(draw, loop, font)
    now = time.monotonic() if now is None else now
    offset = int(now * px_per_sec) % loop_w
    draw.text((-offset, y), loop + loop, font=font, fill=1)


def _list_rows(draw, lines: list[str]) -> None:
    y = 16
    for line in lines[:4]:
        cursor = line.startswith("> ")
        text = _fit(draw, line[2:] if cursor else line.removeprefix("  "),
                    FONT_SMALL, WIDTH - 2)
        if cursor:                 # cursor row: inverted block
            draw.rectangle((0, y - 1, WIDTH, y + 11), fill=1)
            draw.text((2, y), text, font=FONT_SMALL, fill=0)
        else:
            draw.text((2, y), text, font=FONT_SMALL, fill=1)
        y += 12


def _bottom_row(draw, vm: ViewModel, y: int) -> None:
    if vm.hint:
        draw.text((0, y), vm.hint, font=FONT_SMALL, fill=1)
        return
    if vm.progress is not None:  # playing: pos | speed | dur (or pending entry)
        draw.text((0, y), vm.time_pos, font=FONT_SMALL, fill=1)
        if vm.meta_left:
            draw.text(((WIDTH - _w(draw, vm.meta_left, FONT_SMALL)) // 2, y),
                      vm.meta_left, font=FONT_SMALL, fill=1)
        right = vm.meta_right or vm.time_dur
        draw.text((WIDTH - _w(draw, right, FONT_SMALL), y),
                  right, font=FONT_SMALL, fill=1)
    else:                        # idle: meta line
        draw.text((0, y), vm.meta_left, font=FONT_SMALL, fill=1)
        if vm.meta_right:
            draw.text((WIDTH - _w(draw, vm.meta_right, FONT_SMALL), y),
                      vm.meta_right, font=FONT_SMALL, fill=1)


def render(vm: ViewModel, now: float | None = None) -> Image.Image:
    """The one true OLED layout. Same ViewModel the terminal UI shows.

    `now` fixes the marquee position; leave it None for live rendering.
    """
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    _status_bar(draw, vm)

    if vm.lines:
        _list_rows(draw, vm.lines)
        if vm.hint:
            draw.rectangle((0, 52, WIDTH, HEIGHT), fill=0)
            draw.text((0, 52), vm.hint, font=FONT_SMALL, fill=1)
        return img

    _marquee_px(draw, 15, vm.title, FONT_TITLE, now=now)
    if vm.progress is not None:
        draw.rectangle((0, 34, WIDTH - 1, 39), outline=1, fill=0)
        fill_w = round(max(0.0, min(1.0, vm.progress)) * (WIDTH - 3))
        if fill_w:
            draw.rectangle((1, 35, 1 + fill_w, 38), fill=1)
        _bottom_row(draw, vm, 44)
    else:
        if vm.subtitle:
            draw.text((0, 34), _fit(draw, vm.subtitle, FONT_SMALL),
                      font=FONT_SMALL, fill=1)
        _bottom_row(draw, vm, 52)
    return img


class OledDisplay:
    """Display backend for the real SSD1309 (or any luma device)."""

    def __init__(self, device=None):
        if device is None:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1309

            device = ssd1309(i2c(port=1, address=0x3C))
        self.device = device
        self._last: bytes | None = None

    def close(self) -> None:
        """Blank the panel.

        luma clears the display at interpreter exit, but on shutdown the
        process is killed before that runs -- and a Pi that has halted still
        powers its 3.3 V rail, so the OLED holds its last frame indefinitely.
        The device looks switched on when it is not, and on battery it draws
        current for the privilege. A dark panel is what "off" looks like.
        """
        try:
            self.device.hide()
            self.device.clear()
        except Exception:                       # noqa: BLE001
            pass                                # already going down

    def render(self, vm: ViewModel) -> None:
        # Pushing 1 KB over I2C costs ~96 ms at 100 kHz, and the app renders
        # every 50 ms tick — so an unconditional write pins the whole loop at
        # about 6 Hz. The keypad is scanned in that same loop, and a press
        # shorter than one iteration is simply never seen: the panel makes the
        # buttons feel broken.
        #
        # Drawing costs 1.3 ms, so draw always and compare the pixels: the
        # write only happens when the panel would actually change. Comparing
        # the rendered image rather than the ViewModel keeps the title marquee
        # scrolling, since that animates on the clock with the model unchanged.
        image = render(vm).convert(self.device.mode)
        data = image.tobytes()
        if data == self._last:
            return
        self._last = data
        self.device.display(image)
