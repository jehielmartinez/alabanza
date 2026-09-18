# Biblia — verses on the projector

> **Status: BUILT, 2026-09-14; verified on a projector 2026-09-18**
> (`app/alabanza/bible.py`, `tools/build_bible.py`).
> Every number below was measured on the Zero W demo board (armv6l) unless
> it says otherwise. What changed between the spec and the code is noted
> in place.

A second use for the same box: pick a passage from the Reina-Valera 1960,
put it on HDMI, white serif on black, and step through it as it is read.
No imagery, no chrome. The OLED shows the reference; the projector shows
the words.

## Verdict: yes, and cheaply

It needs **no new video stack**. The app already puts a static PNG on HDMI
between hymns (`Player.show_idle`, SPEC decision 8) by loading the image
into the one mpv instance. A verse slide is the same thing with a different
file: draw the text with Pillow, which the app already ships for the OLED,
write the image to RAM, ask mpv to show it. mpv keeps it up for free — a
still image costs no CPU once loaded, exactly like the screensaver.

Measured on the Zero W, DejaVu Serif, a three-verse slide, black background:

| Step | 1920×1080 | 1280×720 |
|---|---|---|
| Pillow draw (wrap + text) | 460 ms | 340 ms |
| Write as BMP/PPM (uncompressed) | 170 ms | 80 ms |
| Write as PNG (compressed) | 1.0–3.7 s | 330 ms |
| First `import PIL` | 1.3 s, once | |

So a slide is about **half a second from confirm to file on the Zero W**,
and the Zero 2 W will be several times faster. Compressed PNG is out:
uncompressed BMP to tmpfs is ten times cheaper and mpv reads it fine.
2.7 MB per slide in RAM, one slide at a time.

Resources on the board: 426 MB RAM with ~290 MB free while the app runs;
the whole RVR1960 is a 5 MB JSON (66 books, 1,189 chapters, 31,104 verses,
median verse 115 characters, longest 450). Fonts: DejaVu Serif and Serif
Bold are already installed by Pi OS Lite, nothing to vendor.

**The one thing not measured** was mpv actually painting a still image over
HDMI on the Zero W. It was checked on 2026-09-18, and it failed — the
reasoning that made it look safe (the screensavers go through the identical
path) is exactly what hid it, because they are a *different size*.

A still whose size matches the one already on screen is decoded, rendered
and reported shown — mpv logs `first video frame after restart shown` about
0.43 s after the load — and never reaches the panel. Only a load that
changes the video size lands, because that reconfigures the output and
forces a modeset; otherwise the frame sits in the back buffer with nothing
to push it out. Screensavers are 1920×1080 and slides 1280×720, so the
first slide of a reading landed and every one after it did not, while the
panel, the worker and mpv all looked healthy. Confirmed on the board by
alternating sizes deliberately: of `1920, 1280, 1280, 1280, 1920, 1920,
1280`, only the four size changes appeared.

The fix is `player._StillRepaint`: after every still, write `video-zoom` to
0.0001 and back to 0, six times over two seconds. The write forces the
redraw that is the present the still never got. It runs on its own thread —
`Slides._render` calls `show_image` holding its lock, and a sleep there is a
keypress the keypad never sees — and repeats because the load it chases is
asynchronous. A hymn cancels it; video presents its own frames.

Two things worth keeping in mind next time. A projector switched on *after*
the box boots is still no display as far as `_drm_device` is concerned, and
video stays off for the whole session. And `Slides.last_error` used to be
swallowed, which made a failing slide worker indistinguishable from an app
that had stopped asking for slides; it goes to the journal now.

## The text

Source: [dscottpi/bibles](https://github.com/dscottpi/bibles), file
`RVR1960 - Spanish.json`, 5.0 MB. Shape: `{book: {chapter: {verse: text}}}`
plus a stray top-level `"lang": "SPAN"` key. Spot-checked: Salmos has 150
chapters, 119 has 176 verses, "S.Juan" 3:16 reads as printed. Three things
to fix at conversion time, not at runtime:

- **Book names are inconsistent** — `S. Mateo`, `S. Marcos`, `S. Lucas`,
  `S.Juan` (no space), and the file's keys sort alphabetically, not in
  canonical order. The converter carries its own 66-row table: canonical
  order, the name to display (`Juan`, not `S.Juan`), and the short form
  for the OLED (`1 Co`, `Ap`).
- **Verses carry trailing spaces.** The count is 31,104 against the 31,102
  of English Bibles, which turned out not to be a defect: the Reina-Valera
  numbers a few passages differently (3 Juan runs to verse 15). The
  converter strips whitespace and reports any chapter whose verse numbers
  are not 1..n, so a real gap or duplicate is found once, on the laptop,
  instead of on a projector. The download has none.
- **Poetry lost its line breaks**: Salmos 23:2 arrives as `me hará
  descansar;Junto a aguas de reposo`, and 4,893 verses are like it. A line
  of a psalm ends in punctuation and the next starts with a capital, so
  the converter puts a space back at exactly that pair.

Alternatives, all the same text in another wrapper:
[mrk214/bible-data-es-spa](https://github.com/mrk214/bible-data-es-spa) (11
Spanish versions, JSON), [xtiam57/church-utils](https://github.com/xtiam57/church-utils)
(one JSON per chapter, array of arrays — its upstream `bible-json` repo is
gone), [scrollmapper/bible_databases](https://github.com/scrollmapper/bible_databases)
(SQLite, many languages). Pick dscottpi because it is a single file whose
structure is already verified above.

**Copyright.** The repos are MIT-licensed, but MIT covers the packaging,
not the words: the RVR1960 text is held by Sociedades Bíblicas Unidas in
most countries and none of these repos has a licence from them. Church
projection from a downloaded copy is common practice and the same thing
every free Bible app does; it is still the church's call, and the text
must not ship in this public repo. It lives next to the hymn library
(git-ignored), see § Provisioning.

### On-device format

`tools/bible/rvr1960/` — one JSON per book, `NN-nombre.json`, holding a
list of chapters, each a list of verse strings (index 0 = verse 1), plus
`index.json` with the 66 names, short names and chapter counts. Books are
loaded on first use and cached; the whole thing is 5 MB, so even loading
it all would be fine, but per-book files keep the first `Biblia` screen
instant on a core where `json.load` of 5 MB is a second or two. Built once
by `tools/build_bible.py` from the downloaded file; synced by `sync.sh`
without a flag (it is small).

## Controls

Same nineteen inputs, nothing new on the panel, and the encoder does most
of the work — the standing rule from SPEC and `docs/BLUETOOTH.md`. Reached
from the menu as a new row, `Biblia`, between `Buscar por titulo` and
`Reescanear biblioteca`.

The projector shows one thing at a time. While a hymn plays, its video
owns HDMI; choosing `Biblia` then flashes `Detén el himno` and does
nothing, the same answer the Bluetooth scan gives. Stop the hymn, then
open the Bible. Typing a hymn number is a home-screen thing; from any
Bible screen `*` walks back to home first.

### Screen 1 — pick the passage (`BIBLE_PICK`)

Three fields filled in order, one screen: **Libro › Capítulo › Versículo**.

| Control | Libro | Capítulo / Versículo |
|---|---|---|
| Wheel, ▲▼ | scroll the 66 books, wrapping, canonical order — ▲ up the list | ±1, bounded by the book / chapter — ▲ is a higher number |
| `0`–`9` | predictive T9 on the book name, one press per letter, same as the title search (`Juan` = `5826`, `Salmos` = `72`, `Romanos` = `76`) — the list narrows, the wheel picks | type the number |
| Push, `#` | confirm, move to the next field | confirm; on Versículo: **show** |
| `*` | erase a typed digit; with nothing typed, back to the menu | erase a digit; with nothing typed, back a field |

Chapter and verse default to 1, so `Salmos` › push › `23` › push › push
puts Psalm 23 from verse 1 on the wall in five presses. The screen
remembers the last passage shown, so after `*` from the slide the fields
come back filled and the next reading is one edit away.

OLED, 4 rows: status `BIBLIA`; row 2 the reference being built
(`Juan 3:1_`) in the title font; rows 3–5 the book list while on Libro, or
the chapter/verse limits (`150 capítulos`, `36 versículos`) after; hint
`gira y pulsa` on Capítulo and Versículo, and **none on Libro** — turning
and pushing is what the panel does everywhere, and the row buys a third
book instead. A flash message still takes the row while it is up.

### Screen 2 — the slide (`BIBLE_SHOW`)

The app holds a **range** `[first, last]` inside one chapter and renders it
as one slide. It opens as a single verse.

| Control | Does |
|---|---|
| Wheel CW, ▲ | next: the whole range slides forward one verse (16 → 17; 16–18 → 17–19). Past the chapter's end, on to verse 1 of the next chapter |
| Wheel CCW, ▼ | previous, same rule backwards |
| Push, `#` | **add** the next verse to the slide (16 → 16–17). If digits are typed: jump to that verse in this chapter instead, as a single verse |
| `0`–`9` | type a verse number to jump to; `#` shows it |
| `*` | erase a typed digit; else **remove** the last verse of the range; on a single verse, back to Screen 1 |
| `*` held | back to Screen 1 at once, however many verses are up (0.75 s) |
| ◀ ▶ | previous / next chapter, from verse 1 |
| D-pad centre | nothing (no transport here; a hymn cannot play while a slide is up) |

That is the reader's whole vocabulary: turn to follow the reading, push to
put more on the wall, `*` to take it off. A slide holds as many verses as
fit at the minimum type size; a push that would overflow flashes `No cabe
más` and leaves the range alone. Nobody has to think about lines or
pages — the layout is the app's problem.

Holding `*` is the same word said harder: a five-verse reading took five
presses to leave, and the hold does it in one. It adds no function — every
state it skips is one a press would have reached — which is why it does not
count against SPEC's "no long-presses" (see the note there).

▲ raises the verse number and the wheel's clockwise does the same, matching
the home screen, where ▲ is a higher hymn number and clockwise is a higher
one still. The D-pad used to run backwards here, on the reasoning that ▼
moves *down a list*; a verse is a number, not a row, and the hand does not
switch conventions between screens.

OLED: status `BIBLIA`; row 2 the reference in the title font
(`Juan 3:16-18`); rows 3–4 the first words of the first verse, so the
operator can confirm it is the right one without looking at the wall;
hint `* quita · # añade`, in the keypad's own left-to-right order — the
two keys are next to each other on the bottom row, and naming them the
other way round made the operator cross their hand over. The D-pad's ◀ ▶
are not advertised.

Leaving with `*` from a single verse restores the screensaver on HDMI
(`show_idle`), so the wall is never left on a stale verse — including a
slide still being drawn, which is cancelled rather than allowed to land on
top of whatever replaced it.

Row 2 always names the range actually on the wall. A wheel step keeps the
width of the range it moves, so a reading of three verses can walk into
three longer ones that do not fit; the renderer drops the tail, reports how
far it got, and the panel adopts that and says `No cabe más` once. Only the
renderer knows, and it knows half a second late, so the panel takes the
answer when it arrives rather than laying the passage out on the loop
thread to predict it.

## The slide

Deliberately plain, and designed for a projector at the back of a hall,
which is what drove `tools/make_screensaver.py` too:

- **1280×720**, black. mpv scales it to whatever mode the projector took,
  on the VideoCore. 720 is the library's own height, so it costs nothing
  in sharpness anyone can see, and it is a third cheaper to draw on the
  ARM11 than 1080.
- **DejaVu Serif Bold, white**, vendored in `app/alabanza/fonts/` (Bitstream
  Vera licence, alongside it) rather than taken from the board, so a slide
  lays out identically on a laptop and in the tests. Bold because thin
  strokes are the first thing a washed-out projector loses.
- **Margins 8 %** all round, for overscan on old screens.
- **One paragraph per verse**, the verse number as a smaller grey figure at
  the start of its first line, as a printed Bible does. Lines break at
  words, never inside them; text is left-aligned with a ragged right —
  centred wrapped prose is hard to read from a distance.
- **Type size fits the content**: start at 64 px, step down until both the
  width and the height budget hold, floor at 32 px. Below the floor the
  range does not grow (see `No cabe más`). A single verse of median length
  lands around 56 px, three lines; a long one like Ester 8:9 around 40 px;
  Psalm 23 goes up as far as verse 5, at 34 px. The whole psalm is fourteen
  lines and wants 682 px of a 566 px budget — it would need about 26 px
  type, and the floor is there because 32 px is what still reads from the
  back. Verse 6 goes on a second slide, and the panel says `No cabe más`
  rather than dropping it quietly (measured on the Zero W with the real
  text, 2026-09-15).
- **Reference bottom-right, grey, smaller**: `Juan 3:16-18` and, a step
  smaller still, `RVR1960`. The version label is a courtesy to whoever
  is reading along in another edition.
- **A passage that will not fit at the floor is still shown**: verses come
  off the end until what is left fits, and the reference bottom-right names
  the range actually on the wall rather than the one asked for. If even the
  first verse is too long it is drawn anyway and runs off the bottom — a
  black screen in front of a congregation is the worse failure. Only
  reachable by stepping a multi-verse range into longer verses; the
  deliberate case is refused up front with `No cabe más`.
- No transitions, no fades. Swap the file, the wall changes.

## Architecture

Three additions, no changes to what exists beyond a menu row and a new
`Player` method.

**`alabanza/bible.py`** — pure: the book table, `load(book)` with a cache,
`Reference` (book, chapter, first, last) with `next()`, `prev()`, `extend()`,
`shrink()` and clamping, T9 matching of book names reusing
`library.search_t9`'s digit mapping, and `render(reference, size=(1280,720))
-> PIL.Image` with the wrap/fit above. Every piece runs on a laptop and is
Tier 1 testable, including pixel-exact slides, the way `test_screens.py`
tests the OLED.

**Rendering off the loop.** Half a second on the loop thread is the exact
fault `ThreadedDisplay` exists to prevent: the keypad is scanned in that
loop and a press would vanish. So slides are produced by a worker the same
shape as `ThreadedDisplay` — hand it a `Reference`, it renders the newest
one it has been given and drops the rest, writes to
`/dev/shm/alabanza/verse-A.bmp` (alternating A/B, then `os.replace` onto
the name mpv is given, so mpv never opens a half-written file) and calls
`player.show_image(path)`. The OLED shows the new reference at once; the
wall follows ~0.5 s later on the Zero W. Fast turns of the wheel coalesce
into one render, so the board is never asked to draw slides it will not
show.

**`Player.show_image(path)`** — `show_idle` without the random choice: load
the file, mark it as not-a-hymn so `active` stays false, keep
`image-display-duration=inf` as it already is. `show_idle` becomes a caller
of it. No other change to the player.

**`App`** — two new `Mode`s, `BIBLE_PICK` and `BIBLE_SHOW`, their two
handlers and two view builders, the `Biblia` menu row, and `bible_last`
in `Settings` (the last reference, for the prefilled pick screen; written
through the existing debounced atomic save). `_handle_transport` is not
applied in Bible modes, on purpose.

CPU while a slide is up: the same as idle with a screensaver, since mpv
holds a still image. The only cost is the render burst, when nothing else
is running anyway.

## Provisioning

- `tools/build_bible.py` downloads (or takes a path to) the dscottpi JSON
  and writes `tools/bible/rvr1960/`. Runs on the laptop, once. Reports
  verse-count anomalies against the standard table, and **writes nothing
  when it has anything to report** (`--force` overrides a fault already
  understood): the checks are only worth having if a defective build cannot
  reach the card. Chapters and verses are placed by their own number, so a
  gap in the source leaves a hole rather than renumbering everything after
  it.
- `tools/bible/` is **git-ignored**, like `tools/library/` — the text is not
  ours to publish.
- `sync.sh` includes `tools/bible/` by default (5 MB) when this machine has
  it. It is git-ignored, so a clone that has not run `build_bible.py`
  excludes it instead — `--delete` would otherwise erase the copy already on
  the device.
- No new apt packages: `fonts-dejavu-core` is already on Pi OS Lite;
  Pillow is already a dependency. The armv6l Pillow 10.4 pin from piwheels
  is what ran the measurements above.
- `/dev/shm` exists on Pi OS; the app creates its subdirectory at start.

## Tests

Tier 1 (laptop, `pytest`): book table has 66 entries in canonical order and
every name in the source file maps to one row; `Reference` arithmetic at
chapter boundaries and at the ends of the Bible; T9 book matching; wrap
never splits a word and never exceeds the margin; fit picks the same size
for the same text; a long verse floors at 34 px; `extend()` refuses past
the fit; pixel-exact slides for two fixed references, like the OLED screen
tests. The state machine: the five-press Psalm 23 path, `Detén el himno`
while playing, `*` all the way home restores the screensaver.

Tier 2 (device): `tools/bible/` present with 66 files; the render worker
produces a file within 2 s; `show_image` on a connected HDMI.

Per-unit acceptance adds one line to TESTING.md: open Juan 3:16 on the
projector and turn the wheel once.

## What is left

Everything above is built and covered by Tier 1 tests, and the worker was
timed on the Zero W with the real text, through the same code path the app
runs: **0.5–0.8 s per slide** — 760 ms for a lone Juan 3:16, 570 ms for
16–18, 700 ms for five verses of Psalm 23, under 500 ms for the next turn
of the wheel. The first version took 2.8 s for three verses: the size
search laid the passage out seventeen times, measuring every candidate
line. Word widths are now cached per size (Layout.BASIC has no kerning,
so a line is the sum of its words) and the size is found by binary
search, five layouts instead of seventeen.

The one piece of Pillow left on the loop thread is the `fits` check behind
`#`, and it was the expensive kind: a layout at the 32 px floor, which the
size search never reaches for a passage that fits above it, so its word
widths were always cold. Measured on the Zero W through the worker, that
keypress cost **35–53 ms** against a 50 ms tick — a dropped tick on the
worst of them. The worker measures the next verse's words itself, right
after the slide lands, on a thread that has just spent half a second and
has nothing waiting on it; the keypress is **2–12 ms** now. Nothing is
thrown away but the boolean: those same widths are what the next slide is
laid out from.

Not yet done, because HDMI was unplugged on the bench: **seeing a slide on
a projector from the Zero W**. The screensavers go through the identical
`show_image`, so if the projector showed one at the church test this is
proven; otherwise, plug HDMI in, open Menu › Biblia, and look. Step 7 of
TESTING.md's acceptance list is exactly that.

## Open questions

1. **Range across chapters.** The spec keeps a range inside one chapter
   (`Juan 3:35-36`, then wheel to `4:1`). Readings that straddle a chapter
   are rare; allowing them complicates the reference and the OLED line.
   Start without.
2. **Book numbers on the card?** The T9 + wheel path needs no numbers, but
   some churches know the books by their order (1 = Génesis … 66 =
   Apocalipsis). If a volunteer asks for it, typing a two-digit book number
   is a small addition to the Libro field; not in v1.
3. **Zero 2 W resolution.** 1280×720 is chosen for the ARM11. The Zero 2 W
   could draw 1080 in the same time; decide when there is one to measure.
