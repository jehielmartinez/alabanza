"""What the OLED actually shows.

Two different jobs:

* **Golden art** pins every screen's pixels. The goldens are stored as text,
  one character per pixel, so a diff shows you the change instead of "binary
  files differ". Regenerate deliberately with UPDATE_GOLDEN=1.
* **Layout invariants** are the ones that find bugs. Golden files happily
  record a broken screen as the new truth; an invariant does not. Both list
  bugs found so far were "the cursor is on a row the hint covers", which is
  exactly what `test_the_cursor_is_always_on_screen` asserts.
"""

import os
from pathlib import Path

import pytest

from alabanza.app import HINT_ROWS
from alabanza.display import ViewModel
from alabanza.events import Kind
from alabanza.oled import FONT_SMALL, HEIGHT, WIDTH, _fit, render
from alabanza.preview import SCREENS

GOLDEN = Path(__file__).parent / "golden"
FIXED_TIME = 0.0        # marquees scroll with the clock; freeze them


def as_text(image) -> str:
    """The 1-bit frame as one character per pixel — '#' lit, '.' dark."""
    pixels = image.load()
    return "\n".join(
        "".join("#" if pixels[x, y] else "." for x in range(image.width))
        for y in range(image.height)
    ) + "\n"


def check_golden(name: str, vm: ViewModel):
    art = as_text(render(vm, now=FIXED_TIME))
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(art)
        return
    assert path.exists(), f"no golden for {name}; run UPDATE_GOLDEN=1 pytest"
    if path.read_text() != art:
        expected = path.read_text().splitlines()
        actual = art.splitlines()
        rows = [i for i, (a, b) in enumerate(zip(expected, actual)) if a != b]
        pytest.fail(
            f"{name} changed on pixel rows {rows[0]}-{rows[-1]}.\n"
            "expected:\n" + "\n".join(expected[rows[0]: rows[-1] + 1]) +
            "\nactual:\n" + "\n".join(actual[rows[0]: rows[-1] + 1]) +
            "\n\nIf the change is intended: UPDATE_GOLDEN=1 uv run pytest"
        )


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_every_screen_matches_its_golden(name):
    """preview.py's catalogue is the single list of screens; keep it complete."""
    check_golden(name, SCREENS[name])


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_every_screen_is_exactly_the_panel_size(name):
    image = render(SCREENS[name], now=FIXED_TIME)
    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "1", "the SSD1309 is 1-bit; anything else means dithering"


class TestLongTextIsTruncatedNotRunOffTheGlass:
    """Hymn titles are longer than 128 px — "Bienvenida da Jesús" already is —
    so the question is not whether text overflows but whether the renderer
    cuts it honestly. Silently running off the edge looks like a fault."""

    def test_fit_returns_something_that_actually_fits(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new("1", (WIDTH, HEIGHT)))
        long = "Bienvenida da Jesús el Salvador del Mundo"
        fitted = _fit(draw, long, FONT_SMALL)
        assert FONT_SMALL.getlength(fitted) <= WIDTH
        assert fitted.endswith("…"), "a cut must be visible, not silent"

    def test_short_text_is_left_alone(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new("1", (WIDTH, HEIGHT)))
        assert _fit(draw, "Al Cielo Voy", FONT_SMALL) == "Al Cielo Voy"

    def test_a_subtitle_past_the_edge_changes_nothing(self):
        base = ViewModel(title="Himno: 279", subtitle="¡Santo! ¡Santo! ¡Santo!")
        more = ViewModel(title="Himno: 279",
                         subtitle="¡Santo! ¡Santo! ¡Santo! y mucho mas texto")
        assert as_text(render(base, now=0)) == as_text(render(more, now=0))

    def test_a_list_row_past_the_edge_changes_nothing(self):
        base = ViewModel(lines=["> 014 Bienvenida da Jesús"], hint="x")
        more = ViewModel(lines=["> 014 Bienvenida da Jesús el Salvador"], hint="x")
        assert as_text(render(base, now=0)) == as_text(render(more, now=0))


class TestTheCursorIsAlwaysOnScreen:
    """The hint row is drawn over the fourth list row, so a screen that shows
    a hint has three usable rows. Twice now a cursor has been put on the
    invisible fourth — once on the forget confirmation, once on the menu when
    it grew a fifth entry. Neither was visible to a golden test."""

    def assert_visible(self, vm, where):
        if not vm.lines:
            return
        visible = vm.lines[:HINT_ROWS] if vm.hint else vm.lines[:4]
        assert any(row.startswith("> ") for row in visible), (
            f"{where}: the cursor is on a row nobody can see — "
            f"rows={vm.lines!r} hint={vm.hint!r}"
        )

    def test_at_every_position_in_the_main_menu(self, harness):
        rig = harness()
        rig.press(Kind.PUSH)
        for i in range(len(rig.app._menu_items())):
            self.assert_visible(rig.tick(), f"menu position {i}")
            rig.press(Kind.DOWN)

    def test_at_every_position_in_the_bluetooth_list(self, harness):
        rig = harness()
        rig.press(Kind.PUSH)
        while "Bluetooth" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        rig.press(Kind.CONFIRM)
        rig.advance(6)                     # let the scan find everything
        for i in range(8):
            self.assert_visible(rig.tick(), f"bluetooth row {i}")
            rig.press(Kind.DOWN)

    def test_on_the_device_screen_and_its_confirmation(self, harness):
        rig = harness(paired=("AA:BB:CC:00:00:01",))
        rig.press(Kind.PUSH)
        while "Bluetooth" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        rig.press(Kind.CONFIRM)
        while "JBL" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        rig.press(Kind.CONFIRM)
        for i in range(3):
            self.assert_visible(rig.tick(), f"device action {i}")
            rig.press(Kind.DOWN)
        while "Olvidar" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        rig.press(Kind.CONFIRM)
        self.assert_visible(rig.tick(), "forget confirmation (No)")
        rig.press(Kind.DOWN)
        self.assert_visible(rig.tick(), "forget confirmation (Sí)")

    def test_while_scrolling_search_results(self, harness):
        rig = harness()
        rig.press(Kind.PUSH)
        while "Buscar" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        rig.press(Kind.CONFIRM)
        rig.press((Kind.DIGIT, 2))          # a broad query: many results
        for i in range(4):
            self.assert_visible(rig.tick(), f"search result {i}")
            rig.press(Kind.DOWN)


class TestTheOutputIconTellsTheTruth:
    def test_each_output_state_looks_different_at_a_glance(self):
        frames = {
            state: as_text(render(ViewModel(
                output="bluetooth", volume=60, output_state=state), now=0))
            for state in ("ok", "connecting", "down")
        }
        assert len(set(frames.values())) == 3, (
            "connected, connecting and gone must each be distinguishable")

    def test_it_never_blinks(self):
        """A flashing status bar in a dim sanctuary reads as a fault."""
        vm = ViewModel(output="bluetooth", volume=60, output_state="down")
        assert as_text(render(vm, now=0.0)) == as_text(render(vm, now=7.3))


def test_a_long_title_scrolls_rather_than_being_cut(harness):
    """The marquee is time-driven, which is why render() takes a clock."""
    vm = ViewModel(title="279 · ¡Santo! ¡Santo! ¡Santo! Señor Omnipotente")
    frames = {as_text(render(vm, now=t)) for t in (0.0, 1.0, 2.0, 3.0)}
    assert len(frames) > 1, "a title too long to fit must move"
