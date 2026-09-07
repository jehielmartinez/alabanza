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
ASSETS = ROOT / "tools" / "assets"
OUT_DIR = ROOT / "app" / "alabanza" / "assets"

# One entry per image. Add, remove or reword freely and re-run — the layout,
# the type size and the scrim all follow the text.
#
# Lines are broken at the verse's own clauses, never at the margin: scripture
# read from the back of a hall scans far better when each line is a complete
# thought. That is the only rule worth keeping when editing.
#
# `background` is a filename in tools/assets/. Several slides may share one.
#
# The wording below is Reina-Valera 1960 as commonly printed. **Check it
# against your own Bible before this goes in front of anyone** — these were
# written from memory of the standard text, and a misquoted verse on a church
# projector is exactly the kind of error nobody wants to discover in public.
SLIDES = [
    {
        "background": "milky-way.jpg",
        "verse": [
            "Porque de tal manera amó Dios al mundo,",
            "que ha dado a su Hijo unigénito,",
            "para que todo aquel que en él cree,",
            "no se pierda, mas tenga vida eterna.",
        ],
        "reference": "Juan 3:16",
    },
    {
        "background": "above-clouds.jpg",
        "verse": [
            "Venid a mí todos los que estáis trabajados y cargados,",
            "y yo os haré descansar.",
        ],
        "reference": "Mateo 11:28",
    },
    {
        "background": "fjord-light.jpg",
        "verse": [
            "Yo soy la luz del mundo;",
            "el que me sigue, no andará en tinieblas,",
            "sino que tendrá la luz de la vida.",
        ],
        "reference": "Juan 8:12",
    },
    {
        "background": "golden-hills.jpg",
        "verse": [
            "He aquí, yo estoy a la puerta y llamo;",
            "si alguno oye mi voz y abre la puerta,",
            "entraré a él, y cenaré con él, y él conmigo.",
        ],
        "reference": "Apocalipsis 3:20",
    },
    {
        "background": "open-bible.jpg",
        "verse": [
            "Yo soy el camino, y la verdad, y la vida;",
            "nadie viene al Padre, sino por mí.",
        ],
        "reference": "Juan 14:6",
    },
    {
        "background": "empty-tomb.jpg",
        "verse": [
            "No está aquí, pues ha resucitado, como dijo.",
            "Venid, ved el lugar donde fue puesto el Señor.",
        ],
        "reference": "Mateo 28:6",
    },
    {
        "background": "snow-mountains.jpg",
        "verse": [
            "Venid luego, dice Jehová, y estemos a cuenta:",
            "si vuestros pecados fueren como la grana,",
            "como la nieve serán emblanquecidos.",
        ],
        "reference": "Isaías 1:18",
    },
]

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


MAX_SIZE = 96          # a two-line verse should fill the frame, not float in it
MAX_BLOCK = 0.60       # fraction of height the verse may occupy


def _fit(lines: list[str], path: str, width: int) -> ImageFont.FreeTypeFont:
    """Largest size fitting both the margins and the height budget.

    Width alone is not enough. A short verse constrained only by width would
    stay at whatever the starting size was and float in the middle of the
    frame, while a long one that fits horizontally could still run off the
    bottom. Fitting both means the same layout code gives a two-line psalm
    real presence and a six-line passage room to breathe, with no per-verse
    tuning when someone adds one.
    """
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for size in range(MAX_SIZE, 12, -1):
        font = ImageFont.truetype(path, size)
        too_wide = max(draw.textlength(line, font=font) for line in lines) > width
        too_tall = len(lines) * size * LINE_SPACING > H * MAX_BLOCK
        if not (too_wide or too_tall):
            return font
    return ImageFont.truetype(path, 12)


def _text(draw: ImageDraw.ImageDraw, y: int, line: str, font, fill, alpha: int) -> None:
    """Centred, over a soft shadow — the photograph is not a flat backdrop."""
    x = (W - draw.textlength(line, font=font)) / 2
    draw.text((x + 2, y + 3), line, font=font, fill=(0, 0, 0, alpha))
    draw.text((x, y), line, font=font, fill=fill)


def _build(slide: dict) -> Image.Image:
    source = ASSETS / slide["background"]
    if not source.exists():
        raise SystemExit(f"missing background: {source}")
    VERSE = slide["verse"]
    REFERENCE = slide["reference"]

    image = _scrim(_cover(Image.open(source).convert("RGB")), BLOCK_CENTRE)

    usable = W - 2 * MARGIN
    verse_font = _fit(VERSE, SERIF, usable)
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

    return image.convert("RGB")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("screensaver*.png"):
        stale.unlink()

    for i, slide in enumerate(SLIDES, 1):
        out = OUT_DIR / f"screensaver-{i:02d}.png"
        _build(slide).save(out, "PNG", optimize=True)
        print(f"  {out.name}  {slide['reference']:20} "
              f"{out.stat().st_size // 1024:5d} KB")
    print(f"wrote {len(SLIDES)} images to {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
