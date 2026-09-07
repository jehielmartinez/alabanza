"""The control set: 3x4 keypad + 5-way D-pad + encoder, and nothing else.

Four functions have no button of their own (Stop, Speed, Menu, T9 search), so
each one's home is pinned here — these are the assertions that break if the
mapping drifts. See the control table in docs/SPEC.md.
"""

import pytest

from alabanza.app import Mode
from alabanza.events import Kind
from alabanza.settings import Settings


@pytest.fixture
def rig(harness):
    return harness()


class TestStopLivesOnStar:
    """`*` means "clear what is going on": the digit, or else the hymn."""

    def test_it_erases_typed_digits_first(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.type_number(12)
        rig.press(Kind.STAR)
        assert rig.app.entry == "1"
        assert rig.player.active, "erasing a digit must not stop the hymn"

    def test_with_nothing_typed_it_stops_the_hymn(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.press(Kind.STAR)
        assert not rig.player.active

    def test_it_is_harmless_when_nothing_is_happening(self, rig):
        rig.press(Kind.STAR)
        assert not rig.player.active and rig.app.entry == ""


class TestSpeedLivesOnTheDpad:
    """▲▼ adjust the hymn that is playing — exactly when speed is wanted."""

    def playing(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        return rig

    def test_up_and_down_move_in_5_percent_steps(self, rig):
        self.playing(rig)
        rig.press(Kind.UP, Kind.UP)
        assert rig.player.speed == 1.10
        rig.press(Kind.DOWN)
        assert rig.player.speed == 1.05

    def test_it_says_what_the_speed_is(self, rig):
        self.playing(rig)
        rig.press(Kind.UP)
        assert "105%" in rig.message

    def test_it_clamps_to_the_singalong_safe_range(self, rig):
        self.playing(rig)
        rig.press(*[Kind.UP] * 12)
        assert rig.player.speed == 1.25 and "max" in rig.message
        rig.press(*[Kind.DOWN] * 20)
        assert rig.player.speed == 0.75 and "min" in rig.message

    def test_speed_resets_for_the_next_hymn(self, rig):
        self.playing(rig)
        rig.press(Kind.UP, Kind.UP)
        rig.type_number(14)
        rig.press(Kind.CONFIRM)
        assert rig.player.speed == 1.0


class TestTheDpadBrowsesWhenIdle:
    def test_down_walks_forward_and_up_walks_back(self, rig):
        rig.press(Kind.DOWN)
        first = rig.app.browse
        rig.press(Kind.DOWN)
        assert rig.app.browse > first
        rig.press(Kind.UP)
        assert rig.app.browse == first

    def test_browsing_clears_a_half_typed_number(self, rig):
        rig.type_number(27)
        rig.press(Kind.DOWN)
        assert rig.app.entry == ""


class TestTheWheelIsAlwaysVolume:
    def test_it_works_while_idle(self, rig):
        before = rig.player.volume
        rig.press(Kind.WHEEL_CW)
        assert rig.player.volume == before + 2

    def test_it_works_while_playing(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM, Kind.WHEEL_CCW)
        assert rig.player.volume == 78

    def test_the_level_is_remembered_against_the_current_output(self, rig):
        rig.press(Kind.WHEEL_CW)
        assert rig.app.settings.volumes["jack"] == rig.player.volume

    def test_each_output_keeps_its_own_level(self, harness):
        rig = harness(settings=Settings(output="jack"))
        rig.press(Kind.WHEEL_CW, Kind.WHEEL_CW)
        loud = rig.player.volume
        rig.press(Kind.PUSH, Kind.CONFIRM)          # menu -> cycle to Bluetooth
        assert rig.app.settings.output == "bluetooth"
        assert rig.player.volume != loud
        # picking Bluetooth with nothing connected jumps to the BT screen, so
        # step back to the menu before cycling on round to jack
        rig.press(Kind.STAR)
        rig.press(Kind.CONFIRM, Kind.CONFIRM)
        assert rig.app.settings.output == "jack"
        assert rig.player.volume == loud


class TestMenuLivesOnTheEncoderPush:
    def test_push_opens_it_and_star_backs_out(self, rig):
        rig.press(Kind.PUSH)
        assert rig.app.mode is Mode.MENU
        rig.press(Kind.STAR)
        assert rig.app.mode is Mode.SELECT

    def test_it_opens_mid_hymn_without_disturbing_playback(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM, Kind.PUSH)
        assert rig.app.mode is Mode.MENU
        assert rig.player.active and not rig.player.paused

    def test_the_transport_still_works_from_inside_a_menu(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM, Kind.PUSH)
        rig.press(Kind.PLAY_PAUSE)
        assert rig.player.paused, "a menu must never swallow play/pause"
        rig.press(Kind.SEEK_FWD)
        assert rig.player.seeks, "...nor seek"
        assert rig.app.mode is Mode.MENU


class TestSearchLivesInTheMenu:
    """There is no A-D keypad column, so T9 search is a menu entry."""

    def open_search(self, rig):
        rig.press(Kind.PUSH)
        while "Buscar" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        return rig.press(Kind.CONFIRM)

    def test_it_is_reachable_and_digits_become_letters(self, rig):
        self.open_search(rig)
        assert rig.app.mode is Mode.SEARCH
        vm = rig.press((Kind.DIGIT, 2), (Kind.DIGIT, 4), (Kind.DIGIT, 3))
        assert any("Cielo" in row for row in vm.lines)

    def test_confirming_a_result_plays_it(self, rig):
        self.open_search(rig)
        rig.press((Kind.DIGIT, 2), (Kind.DIGIT, 4), (Kind.DIGIT, 3))
        rig.press(Kind.CONFIRM)
        assert rig.player.active
        assert rig.app.mode is Mode.SELECT

    def test_backing_out_of_an_empty_query_leaves_search(self, rig):
        self.open_search(rig)
        rig.press(Kind.STAR)
        assert rig.app.mode is Mode.SELECT


class TestNumberEntry:
    def test_typing_and_confirming_plays(self, rig):
        rig.type_number(279)
        rig.press(Kind.CONFIRM)
        assert rig.player.active

    def test_play_pause_also_starts_the_typed_hymn(self, rig):
        rig.type_number(5)
        rig.press(Kind.PLAY_PAUSE)
        assert rig.player.active

    def test_a_number_that_does_not_exist_says_so(self, rig):
        rig.type_number(999)
        rig.press(Kind.CONFIRM)
        assert not rig.player.active and rig.message

    def test_entry_is_capped_at_three_digits(self, rig):
        rig.type_number(12345)
        assert rig.app.entry == "123"

    def test_you_can_queue_the_next_number_while_a_hymn_plays(self, rig):
        """▲▼ are the speed during playback, so digits are how you queue."""
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.type_number(14)
        vm = rig.press(Kind.CONFIRM)
        assert rig.app.now_playing.number == 14
        assert vm.title.startswith("014")


class TestTheProjectorNeverShowsNothing:
    """SPEC decision 8: HDMI shows the static image on boot, idle and stop,
    and fullscreen video only while a hymn plays. A black screen in a lit
    hall reads as a broken device, so every exit from playback has to put
    the image back — including the one nobody presses a button for."""

    def test_stopping_returns_to_the_image(self, harness):
        rig = harness()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        assert rig.player.active
        rig.press(Kind.STAR)
        assert rig.player.showing_idle

    def test_a_hymn_ending_on_its_own_returns_to_the_image(self, harness):
        """The path with no keypress behind it: the file simply runs out.
        Missed here, HDMI would hold a black frame until someone acted."""
        rig = harness()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.player.finish()
        rig.app.tick()
        assert rig.app.now_playing is None
        assert rig.player.showing_idle


class TestAFrameSurvivesTheHymnEnding:
    """Every player attribute the view reads is a live call into mpv, and a
    hymn can end between two of them. This crashed the device: the progress
    bar read duration once to check it was non-zero and again to divide by
    it, and the file ended in between."""

    def test_a_duration_that_vanishes_mid_frame_does_not_crash(self, harness):
        rig = harness()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.player.position, rig.player.duration = 30.0, 180.0

        # A duration that is truthy when checked and zero when used again --
        # exactly what mpv does as a file unloads.
        readings = iter([180.0, 0.0, 0.0, 0.0, 0.0])
        type(rig.player).duration = property(lambda self: next(readings, 0.0))
        try:
            rig.app.tick()          # must not raise ZeroDivisionError
        finally:
            del type(rig.player).duration


class TestThePanelReturnsToTheStart:
    """After a hymn, the panel has to invite the next number rather than keep
    naming the last one. The number shown when idle comes from `browse`, not
    from `entry`, which is why clearing the typed digits was not enough."""

    def test_a_finished_hymn_leaves_the_panel_ready_for_the_next(self, harness):
        rig = harness()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.player.finish()
        vm = rig.app.tick()
        assert "005" not in vm.title, f"still naming the last hymn: {vm.title!r}"
        assert vm.title == "Himno: ---"

    def test_star_clears_the_hymn_left_on_screen(self, harness):
        """* means "clear what is going on". With nothing typed and nothing
        playing there was nothing left for it to clear, so pressing it did
        visibly nothing while a hymn number sat on the panel."""
        rig = harness()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        rig.press(Kind.STAR)          # stops the hymn
        assert "005" in rig.app.tick().title
        rig.press(Kind.STAR)          # ...and now clears the panel
        assert rig.app.tick().title == "Himno: ---"

    def test_star_still_erases_digits_first(self, harness):
        """The order matters: digits, then playback, then the panel."""
        rig = harness()
        rig.type_number(17)
        rig.press(Kind.STAR)
        assert rig.app.entry == "1"
