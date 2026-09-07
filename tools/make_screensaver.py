"""Build the HDMI idle image: the photograph, darkened, with a verse on it.

    uv run tools/make_screensaver.py

Writes app/alabanza/assets/screensaver.png at 1920x1080 — the built-in image
SPEC.md decision 8 calls for on boot, idle and stop. It is a generator rather
than a hand-made PNG so the verse, the crop and the type can be changed
without redoing the layout by eye.

Designed for a projector at the back of a hall, which drives most of the
choices: a scrim heavy enough that legibility never depends on what is behind
the words, generous leading, and line breaks placed at the verse's own clauses
instead of wherever the width runs out.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "assets" / "idle-background.jpg"
OUT = ROOT / "app" / "alabanza" / "assets" / "screensaver.png"

# Broken at the clauses, not at the margin. Scripture read from a distance
# scans far better when each line is a complete thought.
VERSE = [
    "Porque en él fueron creadas todas las cosas,",
    "las que hay en los cielos y las que hay en la tierra,",
    "visibles e invisibles;",
    "sean tronos, sean dominios,",
    "sean principados, sean potestades;",
    "todo fue creado por medio de él y para él.",
]
REFERENCE = "Colosenses 1:16"

SERIF = "/System/Library/Fonts/Supplemental/Georgia.ttf"
SERIF_ITALIC = "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"

MARGIN = 210           # keeps text clear of projector overscan on old screens
LINE_SPACING = 1.55
BLOCK_CENTRE = 0.60    # fraction of height the text block centres on


def _cover(image: Image.Image) -> Image.Image:
    """Crop to 16:9 and scale to 1920x1080, keeping the mountains.

    The source is 3:2, so ~16% of the height goes. It comes off the bottom
    rather than the middle: that end is windblown grass, which is the busiest
    part of the frame and the worst thing to put words over.
    """
    target = W / H
    w, h = image.size
    if w / h > target:
        new_w = int(h * target)
        box = ((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h)
    else:
        new_h = int(w / target)
        top = int((h - new_h) * 0.28)
        box = (0, top, w, top + new_h)
    return image.crop(box).resize((W, H), Image.LANCZOS)


def _scrim(image: Image.Image, band_centre: float) -> Image.Image:
    """Darken, so the type has a floor to sit on.

    Two layers. A gradient weighted to the bottom gives the frame depth; a
    soft band centred on the text does the actual work. Without the band the
    top lines land on the brightest clouds and the bottom ones on dark ground,
    so the verse reads unevenly — and it is the first line, over the clouds,
    that a washed-out projector loses first.
    """
    image = Image.blend(image, Image.new("RGB", (W, H), (8, 14, 22)), 0.30)

    mask = Image.new("L", (1, H))
    centre = band_centre * H
    reach = H * 0.42
    for y in range(H):
        t = y / (H - 1)
        depth = 0.08 + 0.46 * t ** 1.35                      # bottom-weighted
        near = max(0.0, 1.0 - (abs(y - centre) / reach) ** 2)  # around the text
        mask.putpixel((0, y), int(255 * min(0.88, depth + 0.42 * near)))
    return Image.composite(Image.new("RGB", (W, H), (6, 11, 18)),
                           image, mask.resize((W, H)))


def _fit(lines: list[str], path: str, width: int, start: int) -> ImageFont.FreeTypeFont:
    """Largest size at which the longest line still clears the margins."""
    size = start
    while size > 12:
        font = ImageFont.truetype(path, size)
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        if max(draw.textlength(line, font=font) for line in lines) <= width:
            return font
        size -= 1
    return ImageFont.truetype(path, 12)


def _text(draw: ImageDraw.ImageDraw, y: int, line: str, font, fill, alpha: int) -> None:
    """Centred, over a soft shadow — the photograph is not a flat backdrop."""
    x = (W - draw.textlength(line, font=font)) / 2
    draw.text((x + 2, y + 3), line, font=font, fill=(0, 0, 0, alpha))
    draw.text((x, y), line, font=font, fill=fill)


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing background: {SOURCE}")

    image = _scrim(_cover(Image.open(SOURCE).convert("RGB")), BLOCK_CENTRE)

    usable = W - 2 * MARGIN
    verse_font = _fit(VERSE, SERIF, usable, 64)
    ref_font = ImageFont.truetype(SERIF_ITALIC, int(verse_font.size * 0.62))

    step = int(verse_font.size * LINE_SPACING)
    gap = int(verse_font.size * 1.15)
    block = step * len(VERSE) + gap + ref_font.size
    top = int(H * BLOCK_CENTRE - block / 2)

    # Shadows on their own layer so they blur together rather than each line
    # casting a hard edge over the one below it.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    y = top
    for line in VERSE:
        sx = (W - sdraw.textlength(line, font=verse_font)) / 2
        sdraw.text((sx, y + 4), line, font=verse_font, fill=(0, 0, 0, 190))
        y += step
    ry = y + gap
    rx = (W - sdraw.textlength(REFERENCE, font=ref_font)) / 2
    sdraw.text((rx, ry + 4), REFERENCE, font=ref_font, fill=(0, 0, 0, 190))

    image = Image.alpha_composite(
        image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(9)))

    draw = ImageDraw.Draw(image)
    y = top
    for line in VERSE:
        x = (W - draw.textlength(line, font=verse_font)) / 2
        draw.text((x, y), line, font=verse_font, fill=(247, 249, 250))
        y += step

    x = (W - draw.textlength(REFERENCE, font=ref_font)) / 2
    draw.text((x, y + gap), REFERENCE, font=ref_font, fill=(196, 210, 216))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)}  {W}x{H}  "
          f"verse {verse_font.size}px  ref {ref_font.size}px  "
          f"{OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
