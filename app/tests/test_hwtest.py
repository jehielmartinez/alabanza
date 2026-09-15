"""The hardware-test panel.

Pure Pillow and pure data, so the screens a PCB gets signed off against are
checked here rather than by squinting at a 128x64 panel over someone's
shoulder. The tool itself needs a Pi; none of what it draws does.
"""

from alabanza.events import Event, Kind
from alabanza.hwtest import (
    CELL_H,
    CELL_W,
    CONTROLS,
    KEYPAD_LAYOUT,
    MAP_TOP,
    FONT_BIG,
    SEP_Y,
    State,
    control_for,
    screen,
    splash,
)
from alabanza.oled import HEIGHT, WIDTH

# One event for every control, which is also the sweep an operator does.
EVERY_CONTROL = (
    [Event(Kind.DIGIT, d) for d in range(10)]
    + [Event(Kind.STAR), Event(Kind.CONFIRM), Event(Kind.UP), Event(Kind.DOWN),
       Event(Kind.SEEK_BACK), Event(Kind.SEEK_FWD), Event(Kind.PLAY_PAUSE),
       Event(Kind.WHEEL_CW), Event(Kind.WHEEL_CCW), Event(Kind.PUSH),
       Event(Kind.PUSH_HELD)]
)

# Emitted only by the keyboard backend; there is no key on the panel for them.
_DEV_ONLY = {Kind.RESCAN, Kind.QUIT}
# Proves nothing a push has not already proved.
_IGNORED = {Kind.PUSH_RELEASE, Kind.STAR_HELD}


def swept(events) -> State:
    state = State()
    for event in events:
        control = control_for(event)
        if control is not None:
            state.record(control)
    return state


class TestEveryControlIsAccountedFor:
    def test_every_event_the_panel_can_send_maps_to_a_control(self):
        """Add a Kind to the panel and forget it here, and a real control
        would be untestable — pressed, and the map never fills."""
        for kind in Kind:
            if kind in _DEV_ONLY or kind in _IGNORED:
                continue
            value = 1 if kind is Kind.DIGIT else 0
            assert control_for(Event(kind, value)) is not None, \
                f"{kind.name} does not name a control"

    def test_a_release_is_not_coverage(self):
        assert control_for(Event(Kind.PUSH_RELEASE)) is None

    def test_a_held_star_is_not_coverage_either(self):
        """It is the same contact as the press that started it, which the
        map already counted."""
        assert control_for(Event(Kind.STAR_HELD)) is None

    def test_the_full_sweep_completes_the_map(self):
        state = swept(EVERY_CONTROL)
        assert state.remaining == [], \
            f"unreachable: {[c.id for c in state.remaining]}"
        assert len(state.seen) == len(CONTROLS)

    def test_each_keypad_key_reports_its_own_row_and_column(self):
        """A swapped row is the fault this tool exists to catch, so the pins
        it prints have to come from the key that was actually pressed."""
        one, nine = control_for(Event(Kind.DIGIT, 1)), control_for(Event(Kind.DIGIT, 9))
        assert one.pins != nine.pins
        assert one.pins[0] != nine.pins[0]      # different rows
        assert one.pins[1] != nine.pins[1]      # different columns


class TestThePanel:
    def test_the_frame_is_the_panel(self):
        for image in (splash(), screen(State()), screen(swept(EVERY_CONTROL))):
            assert image.size == (WIDTH, HEIGHT)
            assert image.mode == "1"

    def test_a_pressed_control_is_filled_and_an_unpressed_one_is_not(self):
        """The map is the whole point: a cell has to read as done or not done
        across the room, not on close inspection."""
        state = swept([Event(Kind.DIGIT, 1)])
        pixels = screen(state).convert("L").load()

        def lit(index: int) -> int:
            x, y = index * CELL_W, MAP_TOP
            return sum(1 for j in range(y, y + CELL_H)
                       for i in range(x, x + CELL_W - 1) if pixels[i, j] > 128)

        assert lit(0) > lit(1) * 1.5, \
            "a pressed cell must be obviously fuller than an unpressed one"

    def test_nothing_is_drawn_past_the_glass(self):
        """The map is anchored to the bottom edge; one row too tall and the
        last line of controls is simply invisible on the real panel."""
        assert MAP_TOP + 2 * CELL_H == HEIGHT
        assert len(CONTROLS[12:]) * CELL_W <= WIDTH

    def test_every_control_name_fits_the_big_row(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new("1", (WIDTH, HEIGHT)))
        for control in CONTROLS:
            width = draw.textlength(control.name, font=FONT_BIG)
            assert width <= WIDTH, f"{control.name!r} is {width}px wide"

    def test_the_name_row_clears_the_coverage_map(self):
        """FONT_BIG has descenders — 'Izquierda' is the one that finds them."""
        top = SEP_Y + 3
        ascent, descent = FONT_BIG.getmetrics()
        assert top + ascent + descent <= MAP_TOP

    def test_the_splash_reaches_all_four_edges(self):
        """A border on the outermost pixels is what catches a panel whose
        height or start-line is set wrong — it comes back clipped."""
        pixels = splash().convert("L").load()
        assert pixels[0, 0] and pixels[WIDTH - 1, 0]
        assert pixels[0, HEIGHT - 1] and pixels[WIDTH - 1, HEIGHT - 1]


class TestTheLegendMatchesTheKeypad:
    def test_the_layout_is_the_3x4_the_board_has(self):
        assert len(KEYPAD_LAYOUT) == 4
        assert {len(row) for row in KEYPAD_LAYOUT} == {3}

    def test_the_glyphs_are_one_character_each(self):
        """A cell is 10px and the font is 6px; two characters overflow it."""
        for control in CONTROLS:
            assert len(control.glyph) == 1, control


class FakePanel:
    """A luma device that fails when told to. `.mode` is all luma exposes
    that PanelWriter needs, which is why the writer takes the device."""

    mode = "1"

    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.attempts = 0
        self.written = []

    def display(self, image):
        self.attempts += 1
        if self.attempts in self.fail_on:
            raise OSError(121, "Remote I/O error")
        self.written.append(image.tobytes())


class TestThePanelWriterSurvivesTheBus:
    """The tool died at key 8 with thirteen controls still untested because
    one I2C write raised. A bring-up tool must outlive its display."""

    def test_a_failed_write_does_not_raise(self):
        from alabanza.hwtest import PanelWriter
        writer = PanelWriter(FakePanel(fail_on=[1]))
        assert writer.write(splash()) is False
        assert writer.errors == 1
        assert "Remote I/O error" in writer.last_error

    def test_a_dropped_frame_is_tried_again(self):
        """A failed write cannot count as delivered, or the panel is left
        showing something older than the writer believes is up."""
        from alabanza.hwtest import PanelWriter
        panel = FakePanel(fail_on=[1])
        writer = PanelWriter(panel)
        image = screen(swept([Event(Kind.DIGIT, 1)]))
        assert writer.write(image) is False
        assert writer.write(image) is True, "the same frame was never retried"
        assert writer.frames == 1

    def test_an_unchanged_frame_costs_no_i2c(self):
        """A 1 KB write is ~24 ms at 400 kHz; redrawing an idle screen at
        50 Hz would make the panel the slowest thing in the loop."""
        from alabanza.hwtest import PanelWriter
        panel = FakePanel()
        writer = PanelWriter(panel)
        image = screen(State())
        writer.write(image)
        writer.write(image)
        assert panel.attempts == 1

    def test_it_keeps_going_after_a_glitch(self):
        from alabanza.hwtest import PanelWriter
        panel = FakePanel(fail_on=[2])
        writer = PanelWriter(panel)
        for digit in range(4):
            writer.write(screen(swept([Event(Kind.DIGIT, digit)])))
        assert writer.errors == 1
        assert writer.frames == 3, "a glitch must not stop later frames"
