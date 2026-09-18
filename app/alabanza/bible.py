"""Verses on the projector — the text, the passage, and the slide.

docs/BIBLE.md is the spec. Three things live here, all of them pure:

* `Bible` — the RVR1960 text as tools/build_bible.py lays it out, one JSON
  per book, loaded on first use. Also runs from a dict, for tests.
* `Reference` and the moves on it — a range of verses inside one chapter,
  stepped, extended, shrunk, jumped, always kept inside the text.
* `render()` — the slide: white serif on black, the type sized to fit.

`Slides` at the bottom is the one impure piece: it draws on a thread and
hands the file to the player, for the same reason ThreadedDisplay exists.
Half a second of Pillow on the loop thread is a keypress lost.
"""

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .books import BOOKS, VERSION
from .library import _t9_digits

log = logging.getLogger(__name__)

# --- the slide -------------------------------------------------------------
#
# 1280x720: the library's own height, and a third cheaper to draw on the
# Zero W than 1080 (340 ms against 460). mpv scales it to the projector on
# the VideoCore. Margins of 8% keep the words clear of overscan on old
# screens; the footer sits inside the bottom one.
W, H = 1280, 720
MARGIN_X = int(W * 0.08)
MARGIN_Y = int(H * 0.08)
MAX_SIZE, MIN_SIZE = 64, 32    # px; the floor is what still reads from the back
LINE = 1.35                    # line height, as a multiple of the size
PARA_GAP = 0.5                 # between verses, as a multiple of the size
NUMBER_SCALE = 0.55            # the verse number, relative to the text
FOOTER_SIZE = 28
WHITE, GREY, DIM = (255, 255, 255), (170, 170, 170), (130, 130, 130)

_FONT = Path(__file__).parent / "fonts" / "DejaVuSerif-Bold.ttf"


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    # Layout.BASIC for the reason oled.py gives: Raqm is present on Pi OS and
    # absent on macOS, and a slide must lay out the same on both.
    return ImageFont.truetype(str(_FONT), size, layout_engine=ImageFont.Layout.BASIC)


# --- the text --------------------------------------------------------------

@dataclass(frozen=True)
class Reference:
    """A passage: verses `first`..`last` of one chapter of one book.

    `book` is the index into books.BOOKS; chapter and verses are 1-based, the
    way they are printed. Always a single chapter — a reading that straddles
    one is rare and the label gets complicated (BIBLE.md, open question 1).
    """

    book: int
    chapter: int
    first: int
    last: int

    @property
    def name(self) -> str:
        return BOOKS[self.book][0]

    @property
    def verses(self) -> str:
        return str(self.first) if self.last == self.first else f"{self.first}-{self.last}"

    @property
    def label(self) -> str:
        return f"{self.name} {self.chapter}:{self.verses}"

    @property
    def short_label(self) -> str:
        return f"{BOOKS[self.book][1]} {self.chapter}:{self.verses}"


class Bible:
    """The text, by book, chapter and verse.

    `directory` holds what tools/build_bible.py wrote; `data` is the same
    thing already in memory, {book index: [[verse, ...] per chapter]}, for
    tests and for a machine with no text on it.
    """

    def __init__(self, directory: Path | None = None,
                 data: dict[int, list[list[str]]] | None = None):
        self._dir = directory
        self._cache: dict[int, list[list[str]]] = dict(data or {})
        self._files: dict[int, str] = {}
        self._available = data is not None
        if directory is not None:
            try:
                index = json.loads((directory / "index.json").read_text())
                for i, entry in enumerate(index["books"]):
                    self._files[i] = entry["file"]
                self._available = len(self._files) == len(BOOKS)
            except (OSError, ValueError, KeyError, TypeError):
                self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _book(self, book: int) -> list[list[str]]:
        if book not in self._cache:
            chapters: list[list[str]] = []
            if self._dir is not None and book in self._files:
                try:
                    chapters = json.loads((self._dir / self._files[book]).read_text())
                except (OSError, ValueError):
                    chapters = []
            self._cache[book] = chapters
        return self._cache[book]

    def chapters(self, book: int) -> int:
        return BOOKS[book][2]

    def verses(self, book: int, chapter: int) -> int:
        chapters = self._book(book)
        if 1 <= chapter <= len(chapters):
            return len(chapters[chapter - 1])
        return 0

    def text(self, book: int, chapter: int, verse: int) -> str:
        chapters = self._book(book)
        try:
            return chapters[chapter - 1][verse - 1]
        except IndexError:
            return ""

    # -- moves ---------------------------------------------------------
    #
    # Every move returns a Reference inside the text. The book list wraps
    # both ways -- a knob has no end stop, and Apocalipsis 22 is one click
    # from Génesis 1 that way instead of twelve hundred.

    def clamp(self, ref: Reference) -> Reference:
        book = ref.book % len(BOOKS)
        chapter = min(max(1, ref.chapter), self.chapters(book))
        count = max(1, self.verses(book, chapter))
        first = min(max(1, ref.first), count)
        last = min(max(first, ref.last), count)
        return Reference(book, chapter, first, last)

    def _next_chapter(self, book: int, chapter: int) -> tuple[int, int]:
        if chapter < self.chapters(book):
            return book, chapter + 1
        return (book + 1) % len(BOOKS), 1

    def _prev_chapter(self, book: int, chapter: int) -> tuple[int, int]:
        if chapter > 1:
            return book, chapter - 1
        book = (book - 1) % len(BOOKS)
        return book, self.chapters(book)

    def step(self, ref: Reference, direction: int) -> Reference:
        """The whole range one verse forward or back, keeping its width.

        Off the end of a chapter it continues into the next, at verse 1 --
        the reader who turns the knob is following the text, and the text
        goes on. Off the start, the previous chapter's last verses.
        """
        width = ref.last - ref.first
        if direction > 0:
            if ref.last < self.verses(ref.book, ref.chapter):
                return Reference(ref.book, ref.chapter, ref.first + 1, ref.last + 1)
            book, chapter = self._next_chapter(ref.book, ref.chapter)
            return self.clamp(Reference(book, chapter, 1, 1 + width))
        if ref.first > 1:
            return Reference(ref.book, ref.chapter, ref.first - 1, ref.last - 1)
        book, chapter = self._prev_chapter(ref.book, ref.chapter)
        end = max(1, self.verses(book, chapter))
        return self.clamp(Reference(book, chapter, end - width, end))

    def extend(self, ref: Reference) -> Reference:
        """One more verse on the slide; unchanged at the chapter's end."""
        if ref.last < self.verses(ref.book, ref.chapter):
            return Reference(ref.book, ref.chapter, ref.first, ref.last + 1)
        return ref

    def shrink(self, ref: Reference) -> Reference:
        """One verse fewer; unchanged when it is a single verse."""
        if ref.last > ref.first:
            return Reference(ref.book, ref.chapter, ref.first, ref.last - 1)
        return ref

    def chapter_step(self, ref: Reference, direction: int) -> Reference:
        """Verse 1 of the next or previous chapter, crossing books."""
        if direction > 0:
            book, chapter = self._next_chapter(ref.book, ref.chapter)
        else:
            book, chapter = self._prev_chapter(ref.book, ref.chapter)
        return Reference(book, chapter, 1, 1)

    def jump(self, ref: Reference, verse: int) -> Reference:
        """A single verse of the same chapter, clamped to what exists."""
        return self.clamp(Reference(ref.book, ref.chapter, verse, verse))


def search_books(query: str) -> list[int]:
    """Book indices whose name has a word starting with these T9 digits --
    the same predictive search the hymn titles use. Empty query: all 66."""
    if not query:
        return list(range(len(BOOKS)))
    return [i for i, (name, _, _) in enumerate(BOOKS)
            if any(_t9_digits(word).startswith(query) for word in name.split())]


# --- layout ----------------------------------------------------------------

@dataclass(frozen=True)
class _Run:
    x: int
    y: int
    text: str
    size: int
    fill: tuple[int, int, int]


@lru_cache(maxsize=50000)
def _width(word: str, size: int) -> float:
    """One word's advance at one size. Layout.BASIC has no kerning, so a
    line's width is the sum of its words' -- which lets a passage be wrapped
    from a table of word widths instead of measuring every candidate line.
    On the Zero W that was the difference between 2.8 s and a fraction of
    it for a three-verse slide: the verses either side of a reading share
    nearly all their words, and the sizes tried share all of them."""
    return _font(size).getlength(word)


def _wrap(text: str, size: int, width: int, indent: int) -> list[str]:
    """Break at words, never inside one. The first line is `indent` px
    shorter to leave room for the verse number."""
    lines: list[str] = []
    current: list[str] = []
    used = 0.0
    space = _width(" ", size)
    room = width - indent
    for word in text.split():
        w = _width(word, size)
        if current and used + space + w > room:
            lines.append(" ".join(current))
            current, used, room = [word], w, width
        else:
            used += (space + w) if current else w
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _runs(bible: Bible, ref: Reference, size: int) -> tuple[list[_Run], bool]:
    """Every run of text on the slide at this type size, and whether it fits
    the height budget. The runs are laid out either way: a passage that will
    not fit is still drawn, running off the bottom, rather than not drawn."""
    number_size = int(size * NUMBER_SCALE)
    width = W - 2 * MARGIN_X
    budget = H - 2 * MARGIN_Y - FOOTER_SIZE - 12
    line_h, gap = int(size * LINE), int(size * PARA_GAP)
    runs: list[_Run] = []
    y = MARGIN_Y
    for verse in range(ref.first, ref.last + 1):
        number = str(verse)
        indent = int(_width(number, number_size)) + int(size * 0.3)
        lines = _wrap(bible.text(ref.book, ref.chapter, verse), size, width, indent)
        if not lines:
            continue
        # the number sits on the first line's baseline, a little above it
        runs.append(_Run(MARGIN_X, y + int(size * (1 - NUMBER_SCALE) * 0.6),
                         number, int(size * NUMBER_SCALE), GREY))
        for i, line in enumerate(lines):
            runs.append(_Run(MARGIN_X + (indent if i == 0 else 0), y, line, size, WHITE))
            y += line_h
        y += gap
    used = y - gap - MARGIN_Y
    return runs, used <= budget


def _layout(bible: Bible, ref: Reference, size: int) -> list[_Run] | None:
    """The runs at this size, or None if the passage does not fit at it."""
    runs, fitted = _runs(bible, ref, size)
    return runs if fitted else None


def fits(bible: Bible, ref: Reference) -> bool:
    """Whether the passage fits the slide at the smallest allowed type."""
    return _layout(bible, ref, MIN_SIZE) is not None


def best_size(bible: Bible, ref: Reference) -> int | None:
    """The largest even size from MIN_SIZE to MAX_SIZE at which the passage
    fits, or None. Fitting is monotonic in the size, so this is a binary
    search: five layouts instead of seventeen, which matters on one ARM11
    core."""
    best = None
    low, high = MIN_SIZE, MAX_SIZE
    while low <= high:
        mid = ((low + high) // 2) & ~1
        if _layout(bible, ref, mid) is None:
            high = mid - 2
        else:
            best, low = mid, mid + 2
    return best


def render(bible: Bible, ref: Reference) -> Image.Image:
    """The slide alone, for tests and for anything that already knows what
    it asked for is what it will get."""
    return render_slide(bible, ref)[0]


def render_slide(bible: Bible, ref: Reference) -> tuple[Image.Image, Reference]:
    """The slide, and the reference actually on it. The largest type that
    fits, down to MIN_SIZE -- and at MIN_SIZE regardless, so a passage that
    somehow got too long is cut off at the bottom rather than not shown at
    all. The returned reference is the one asked for unless verses had to
    come off the end for room, which is the panel's cue to say the same
    thing the wall does."""
    size = best_size(bible, ref)
    if size:
        runs, shown = _layout(bible, ref, size), ref
    else:
        runs, shown = _layout_regardless(bible, ref)
    image = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    for run in runs:
        draw.text((run.x, run.y), run.text, font=_font(run.size), fill=run.fill)
    # `shown`, not `ref`: if the last verses had to be dropped the footer
    # says so, rather than promising the congregation a verse that is not
    # on the wall.
    footer = f"{shown.label} · {VERSION}"
    footer_font = _font(FOOTER_SIZE)
    # the footer sits a little way into the bottom margin, leaving the
    # verses the room; 8% was for overscan and the footer can afford to lose
    draw.text((W - MARGIN_X - draw.textlength(footer, font=footer_font),
               H - MARGIN_Y - FOOTER_SIZE + 12), footer, font=footer_font, fill=DIM)
    return image, shown


def _layout_regardless(bible: Bible, ref: Reference) -> tuple[list[_Run], Reference]:
    """MIN_SIZE with the height check waived: drop verses off the end until
    what is left fits, and if even the first one does not, draw it anyway and
    let it run off the bottom. Returns the runs and the reference they cover,
    which is what the footer has to name -- a black slide, or one silently
    missing its last verse, is worse than one that overflows."""
    trimmed = ref
    while trimmed.last > trimmed.first and _layout(bible, trimmed, MIN_SIZE) is None:
        trimmed = bible.shrink(trimmed)
    return _runs(bible, trimmed, MIN_SIZE)[0], trimmed


# --- the worker ------------------------------------------------------------

def _slide_dir() -> Path:
    """RAM if the machine has it mounted, else the temp dir. A slide is
    2.7 MB uncompressed and the SD card should never see one."""
    base = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
    directory = base / "alabanza-slides"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class Slides:
    """Draws slides off the loop thread and puts them on HDMI.

    Same shape as ThreadedDisplay: requests coalesce, so a fast turn of the
    wheel renders the reference it lands on and none of the ones it passed.
    Each slide goes to a temp name and is renamed into place, so mpv never
    opens a half-written file; the two final names alternate so a reload
    is always a different path from the one on screen.

    A render already under way is abandoned if the reference it was drawing
    stops being the one wanted -- superseded by a later `show`, or dropped by
    `cancel` when the operator leaves the slide screen. Half a second is long
    enough to walk away from, and a slide that lands after that would sit on
    the projector until the next load.

    `threaded=False` renders inline, for tests and for measuring.
    """

    def __init__(self, player, bible: Bible, directory: Path | None = None,
                 threaded: bool = True):
        self._player = player
        self._bible = bible
        self._dir = directory or _slide_dir()
        self._which = 0
        self._pending: Reference | None = None
        self._generation = 0
        # what the last slide was asked for, and what it could actually
        # carry; the app reads it to keep the panel honest about the wall
        self.drawn: tuple[Reference, Reference] | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.last_error: Exception | None = None
        self._thread = None
        if threaded:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="alabanza-slides")
            self._thread.start()

    def show(self, ref: Reference) -> None:
        with self._lock:
            self._generation += 1
            generation = self._generation
            if self._thread is not None:
                self._pending = ref
        if self._thread is None:
            self._render(ref, generation)
        else:
            self._wake.set()

    def cancel(self) -> None:
        """Abandon whatever is queued or drawing.

        Called by whoever is about to put something else on HDMI -- the
        screensaver on the way out of the slide screen, a hymn on the way
        into one. Returns only once an in-flight render is past the point
        where it could call `show_image`, so the caller's own load is the
        last word and stays on screen.
        """
        with self._lock:
            self._pending = None
            self._generation += 1

    def _render(self, ref: Reference, generation: int) -> None:
        tmp = self._dir / "verse.tmp"
        image, shown = render_slide(self._bible, ref)
        image.save(tmp, format="BMP")
        # Everything that decides what is on screen happens under the lock,
        # including the name flip: a discarded render must not consume a
        # slot, or the next one reuses the path mpv already has open.
        with self._lock:
            if generation != self._generation:
                return                      # cancelled, or superseded, while it drew
            self._which ^= 1
            final = self._dir / f"verse-{self._which}.bmp"
            os.replace(tmp, final)
            self.drawn = (ref, shown)
            self._player.show_image(final)

    def _warm_the_next_fit(self, generation: int) -> None:
        """Measure the words `#` would add, here instead of on the loop thread.

        `fits` asks whether a range still holds at MIN_SIZE, and the size
        search never evaluates MIN_SIZE for a passage that fits above it --
        so the word widths that answer costs are reliably cold, and the loop
        thread paid 24-38 ms of Pillow for them on the Zero W against a
        50 ms tick. They cost the same here, on a thread that has just spent
        half a second and has nothing waiting on it, and leave the keypress
        10-15 ms for a warm lookup.

        Only the result is thrown away, never the work: the same widths are
        what the next slide is laid out from. Superseded means the operator
        has already moved, so the request behind this one matters more.
        """
        with self._lock:
            if generation != self._generation or self.drawn is None:
                return
            ref = self.drawn[1]         # what is on the wall, trim included
        more = self._bible.extend(ref)
        if more != ref:                 # at the chapter's end there is nothing to add
            fits(self._bible, more)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.2)
            self._wake.clear()
            with self._lock:
                ref, self._pending = self._pending, None
                generation = self._generation
            if ref is None:
                continue
            try:
                self._render(ref, generation)
                self._warm_the_next_fit(generation)
            except Exception as exc:            # noqa: BLE001
                self.last_error = exc           # a bad slide must not stop the hymns
                # ...but it must not be silent either. Kept to itself, this
                # is indistinguishable from the app never asking for a
                # slide, and that is a long evening with a projector.
                log.exception("slide failed for %s", ref)

    def close(self) -> None:
        self.cancel()           # nothing lands on HDMI after the app is down
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
