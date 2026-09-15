"""The Bible screens, driven the way the panel drives them — docs/BIBLE.md.

Same nineteen inputs as everything else. Psalm 23 from the menu is five
presses; from then on the wheel follows the reading, # puts one more verse
on the wall, * takes one off.
"""

import pytest

from alabanza.app import HOLD_STALE, PICKER_HOLD, Mode
from alabanza.bible import Bible, Reference
from alabanza.books import BOOKS
from alabanza.events import Kind

from conftest import make_bible

JUAN = next(i for i, (n, _, _) in enumerate(BOOKS) if n == "Juan")
SALMOS = next(i for i, (n, _, _) in enumerate(BOOKS) if n == "Salmos")


@pytest.fixture
def rig(harness):
    return harness(bible=make_bible(verses_per_chapter=6))


def open_bible(rig):
    rig.press(Kind.PUSH, Kind.PUSH_RELEASE)         # menu
    rig.press(Kind.DOWN, Kind.DOWN, Kind.DOWN)      # Salida, Bluetooth, Buscar, Biblia
    assert "Biblia" in rig.cursor_row()
    return rig.press(Kind.CONFIRM)


class TestGettingThere:
    def test_it_is_a_menu_row(self, rig):
        open_bible(rig)
        assert rig.app.mode is Mode.BIBLE_PICK

    def test_without_the_text_the_menu_says_so(self, harness):
        rig = harness()                                  # no bible
        open_bible(rig)
        assert rig.app.mode is Mode.MENU
        assert "Sin Biblia" in rig.message

    def test_a_playing_hymn_keeps_the_projector(self, rig):
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        assert rig.player.active
        open_bible(rig)
        assert rig.app.mode is Mode.MENU
        assert "Detén el himno" in rig.message

    def test_star_walks_back_to_the_menu(self, rig):
        open_bible(rig)
        rig.press(Kind.STAR)
        assert rig.app.mode is Mode.MENU


class TestPickingAPassage:
    def test_psalm_23_is_five_presses(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 7), (Kind.DIGIT, 2), (Kind.DIGIT, 5))   # Sal
        assert rig.cursor_row() == "> Salmos"
        rig.press(Kind.PUSH)                                           # 1
        assert "Capítulo" in rig.cursor_row()
        rig.press((Kind.DIGIT, 2), (Kind.DIGIT, 3))                    # 2, 3
        rig.press(Kind.PUSH)                                           # 4
        assert "Versículo" in rig.cursor_row()
        vm = rig.press(Kind.PUSH)                                      # 5
        assert rig.app.mode is Mode.BIBLE_SHOW
        assert rig.slides.shown == [Reference(SALMOS, 23, 1, 1)]
        assert vm.title == "Salmos 23:1"

    def test_the_wheel_scrolls_the_books_and_wraps(self, rig):
        open_bible(rig)
        assert rig.cursor_row() == "> Génesis"
        rig.press(Kind.WHEEL_CCW)
        assert rig.cursor_row() == "> Apocalipsis"
        rig.press(Kind.WHEEL_CW, Kind.WHEEL_CW)
        assert rig.cursor_row() == "> Éxodo"

    def test_the_book_list_spends_the_hint_row_on_a_third_book(self, rig):
        """Two rows of 66 books is a keyhole, and "turn and push" is what
        the panel does on every screen -- so Libro carries no hint."""
        vm = open_bible(rig)
        assert vm.hint == ""
        assert vm.lines == ["Libro: _", "> Génesis", "  Éxodo", "  Levítico"]

    def test_a_flash_still_takes_that_row(self, rig):
        """It is worth a book for the seconds it is up."""
        open_bible(rig)
        rig.press((Kind.DIGIT, 9), (Kind.DIGIT, 9), (Kind.DIGIT, 9))
        vm = rig.press(Kind.PUSH)
        assert "Sin resultados" in vm.hint

    def test_t9_narrows_and_star_erases(self, rig):
        open_bible(rig)
        vm = rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8))       # Ju
        assert vm.lines[0] == "Libro: 58_"
        assert rig.cursor_row() == "> Jueces"
        rig.press(Kind.WHEEL_CW)
        assert rig.cursor_row() == "> Lucas"                   # Lu is 58 too
        vm = rig.press((Kind.DIGIT, 2), (Kind.DIGIT, 6))       # Juan, not Lucas
        assert rig.cursor_row(vm) == "> Juan"
        rig.press(Kind.STAR, Kind.STAR)
        vm = rig.press(Kind.STAR, Kind.STAR)
        assert vm.lines[0] == "Libro: _"
        assert rig.app.mode is Mode.BIBLE_PICK

    def test_no_match_says_so_and_stays(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 9), (Kind.DIGIT, 9), (Kind.DIGIT, 9))
        rig.press(Kind.PUSH)
        assert "Sin resultados" in rig.message
        assert rig.app.pick_field == 0

    def test_the_wheel_moves_the_chapter_within_the_book(self, rig):
        open_bible(rig)
        rig.press(Kind.PUSH)                            # Génesis
        vm = rig.press(Kind.WHEEL_CCW)
        assert "Capítulo 50" in rig.cursor_row(vm)      # wrapped
        vm = rig.press(Kind.WHEEL_CW)
        assert "Capítulo 1" in rig.cursor_row(vm)

    def test_a_chapter_past_the_end_is_clamped_and_said(self, rig):
        open_bible(rig)
        rig.press(Kind.PUSH)
        rig.press((Kind.DIGIT, 9), (Kind.DIGIT, 9), Kind.PUSH)
        assert "Máximo 50" in rig.message
        assert rig.app.pick_chapter == 50

    def test_a_zero_is_told_about_the_other_end(self, rig):
        """`0` is a real key: answering it with "Máximo 50" names the bound
        it did not miss, and reads as the app not understanding the press."""
        open_bible(rig)
        rig.press(Kind.PUSH)
        rig.press((Kind.DIGIT, 0), Kind.PUSH)
        assert "Mínimo 1" in rig.message
        assert rig.app.pick_chapter == 1

    def test_a_chapter_with_no_text_says_that_instead(self, harness):
        """A book file that did not load has no verses, so neither bound is
        the answer -- and "Máximo 0" is not a sentence."""
        empty = Bible(data={JUAN: [[]]})
        rig = harness(bible=empty)
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)
        rig.press((Kind.DIGIT, 1), Kind.PUSH)          # chapter 1
        rig.press((Kind.DIGIT, 4), Kind.PUSH)          # ...which has no verses
        assert "Sin texto" in rig.message

    def test_star_erases_a_digit_then_backs_a_field(self, rig):
        open_bible(rig)
        rig.press(Kind.PUSH, (Kind.DIGIT, 4))
        assert rig.app.pick_entry == "4"
        rig.press(Kind.STAR)
        assert rig.app.pick_entry == "" and rig.app.pick_field == 1
        rig.press(Kind.STAR)
        assert rig.app.pick_field == 0

    def test_it_reopens_where_the_reader_left_off(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)   # Juan
        rig.press((Kind.DIGIT, 3), Kind.PUSH, (Kind.DIGIT, 4), Kind.PUSH)          # 3:4
        assert rig.app.settings.bible_last == [JUAN, 3, 4]
        rig.press(Kind.STAR)                       # slide -> pick, prefilled
        assert rig.app.mode is Mode.BIBLE_PICK
        assert rig.cursor_row() == "> Juan"
        rig.press(Kind.PUSH)
        assert "Capítulo 3" in rig.cursor_row()

    def test_choosing_another_book_starts_it_at_one(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)
        rig.press((Kind.DIGIT, 3), Kind.PUSH, (Kind.DIGIT, 4), Kind.PUSH)
        rig.press(Kind.STAR)
        rig.press((Kind.DIGIT, 7), (Kind.DIGIT, 2), (Kind.DIGIT, 5), Kind.PUSH)   # Salmos
        assert (rig.app.pick_chapter, rig.app.pick_verse) == (1, 1)


class TestTheNumberFields:
    """Capítulo and Versículo are numbers, so ▲ raises them — the book list
    above them is a list, so ▲ moves up it."""

    def test_up_raises_the_chapter(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)
        assert rig.app.pick_chapter == 1
        rig.press(Kind.UP)
        assert rig.app.pick_chapter == 2
        rig.press(Kind.DOWN)
        assert rig.app.pick_chapter == 1

    def test_up_raises_the_verse(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)
        rig.press((Kind.DIGIT, 3), Kind.PUSH)
        assert rig.app.pick_verse == 1
        rig.press(Kind.UP)
        assert rig.app.pick_verse == 2

    def test_the_book_list_still_moves_like_a_list(self, rig):
        """▲ goes up the 66 books, as it does on every other list screen."""
        open_bible(rig)
        rig.press(Kind.DOWN)
        assert rig.app.pick_cursor == 1
        rig.press(Kind.UP)
        assert rig.app.pick_cursor == 0


class TestOnTheWall:
    @pytest.fixture
    def showing(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)   # Juan
        rig.press((Kind.DIGIT, 3), Kind.PUSH, (Kind.DIGIT, 2), Kind.PUSH)          # 3:2
        rig.slides.shown.clear()
        return rig

    def test_the_wheel_follows_the_reading(self, showing):
        rig = showing
        rig.press(Kind.WHEEL_CW)
        assert rig.app.bible_ref == Reference(JUAN, 3, 3, 3)
        rig.press(Kind.WHEEL_CCW, Kind.WHEEL_CCW)
        assert rig.app.bible_ref == Reference(JUAN, 3, 1, 1)
        assert len(rig.slides.shown) == 3

    def test_walking_off_drops_a_slide_still_drawing(self, showing):
        """* goes back to the picker and the screensaver goes up. A render
        started by the last turn of the wheel must not land on top of it."""
        rig = showing
        rig.press(Kind.WHEEL_CW)
        rig.press(Kind.STAR)
        assert rig.app.mode is Mode.BIBLE_PICK
        assert rig.player.showing_idle
        assert rig.slides.cancelled == 1

    def test_the_dpad_raises_the_verse_number_with_up(self, showing):
        """A verse number is a number, not a list row: ▲ means a later
        verse, the way it means a higher hymn number on the home screen."""
        rig = showing
        rig.press(Kind.UP)
        assert rig.app.bible_ref == Reference(JUAN, 3, 3, 3)
        rig.press(Kind.DOWN)
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 2)

    def test_the_wheel_and_the_dpad_agree(self, showing):
        """Clockwise and ▲ are the same direction -- they were not, and the
        wheel was the one that matched the rest of the panel."""
        rig = showing
        rig.press(Kind.WHEEL_CW)
        after_wheel = rig.app.bible_ref
        rig.press(Kind.WHEEL_CCW, Kind.UP)
        assert rig.app.bible_ref == after_wheel

    def test_hash_adds_a_verse_and_star_takes_it_off(self, showing):
        rig = showing
        vm = rig.press(Kind.CONFIRM)
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 3)
        assert vm.title == "Juan 3:2-3"
        rig.press(Kind.PUSH)
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 4)
        rig.press(Kind.STAR)
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 3)
        assert rig.app.mode is Mode.BIBLE_SHOW

    def test_the_panel_says_what_the_wall_could_fit(self, showing):
        """A stepped range can walk into verses too long for the slide, and
        the renderer drops the tail. The title must not go on promising a
        verse the congregation cannot see."""
        rig = showing
        vm = rig.press(Kind.CONFIRM)                    # # -> Juan 3:2-3
        assert vm.title == "Juan 3:2-3"
        # half a second later the worker reports what actually went up
        rig.slides.drawn = (Reference(JUAN, 3, 2, 3), Reference(JUAN, 3, 2, 2))
        vm = rig.tick()
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 2)
        assert vm.title == "Juan 3:2"
        assert "No cabe más" in rig.message

    def test_an_older_report_does_not_undo_a_fresh_extend(self, showing):
        """# widens the reading and the slide for it takes half a second;
        the report still sitting there is for the narrower one before it."""
        rig = showing
        rig.slides.drawn = (Reference(JUAN, 3, 2, 2), Reference(JUAN, 3, 2, 2))
        vm = rig.press(Kind.CONFIRM)                    # # -> Juan 3:2-3
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 3)
        assert vm.title == "Juan 3:2-3", "not trimmed back by a stale report"

    def test_holding_star_goes_straight_back_to_the_picker(self, showing):
        """Five verses up used to be five presses of * to leave. The hold is
        the same key meaning the same thing, taken all the way."""
        rig = showing
        rig.press(Kind.CONFIRM, Kind.CONFIRM, Kind.CONFIRM)     # Juan 3:2-5
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 5)
        rig.press(Kind.STAR)                                    # down: 3:2-4
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 4)
        rig.clock.advance(PICKER_HOLD)
        rig.press(Kind.STAR_HELD)
        assert rig.app.mode is Mode.BIBLE_PICK
        assert rig.player.showing_idle, "and the wall is back to the screensaver"
        assert rig.slides.cancelled >= 1, "a slide still drawing is dropped"

    def test_the_picker_opens_where_the_reading_was(self, showing):
        rig = showing
        rig.press(Kind.CONFIRM)                                 # Juan 3:2-3
        rig.press(Kind.STAR)
        rig.clock.advance(PICKER_HOLD)
        rig.press(Kind.STAR_HELD)
        assert (rig.app.pick_book, rig.app.pick_chapter) == (JUAN, 3)

    def test_a_quick_star_is_still_just_one_verse_off(self, showing):
        """The hold must not fire on a normal press, or * stops being usable
        for what it is mostly for."""
        rig = showing
        rig.press(Kind.CONFIRM, Kind.CONFIRM)                   # Juan 3:2-4
        rig.press(Kind.STAR)
        rig.clock.advance(PICKER_HOLD - 0.1)
        rig.tick()
        assert rig.app.mode is Mode.BIBLE_SHOW
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 3)

    def test_keepalives_that_stop_are_not_a_hold(self, showing):
        """A backend that cannot report holding at all must not look like
        one that is holding forever."""
        rig = showing
        rig.press(Kind.CONFIRM)
        rig.press(Kind.STAR)
        rig.clock.advance(HOLD_STALE + 0.1)                     # nothing since
        rig.tick()
        rig.clock.advance(PICKER_HOLD)
        rig.tick()
        assert rig.app.mode is Mode.BIBLE_SHOW

    def test_the_range_moves_as_one(self, showing):
        rig = showing
        rig.press(Kind.CONFIRM, Kind.WHEEL_CW)
        assert rig.app.bible_ref == Reference(JUAN, 3, 3, 4)

    def test_it_will_not_add_past_the_chapter(self, showing):
        rig = showing
        rig.press((Kind.DIGIT, 6), Kind.CONFIRM)           # jump to the last verse
        assert rig.app.bible_ref == Reference(JUAN, 3, 6, 6)
        rig.press(Kind.CONFIRM)
        assert "Fin del capítulo" in rig.message
        assert rig.app.bible_ref == Reference(JUAN, 3, 6, 6)

    def test_it_will_not_add_what_does_not_fit(self, harness):
        long = make_bible(verses_per_chapter=6)
        long._cache[JUAN] = [["palabra " * 120] * 6] * 21
        rig = harness(bible=long)
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)
        rig.press(Kind.PUSH, Kind.PUSH)                    # 1:1
        rig.press(Kind.CONFIRM)
        assert "No cabe más" in rig.message
        assert rig.app.bible_ref == Reference(JUAN, 1, 1, 1)

    def test_digits_then_hash_jump_within_the_chapter(self, showing):
        rig = showing
        vm = rig.press((Kind.DIGIT, 5))
        assert vm.status_right == "5_"
        rig.press(Kind.CONFIRM)
        assert rig.app.bible_ref == Reference(JUAN, 3, 5, 5)

    def test_a_jump_past_the_end_lands_on_the_last_verse(self, showing):
        rig = showing
        rig.press((Kind.DIGIT, 9), Kind.CONFIRM)
        assert rig.app.bible_ref == Reference(JUAN, 3, 6, 6)
        assert "Máximo 6" in rig.message

    def test_a_jump_to_zero_is_told_about_the_other_end(self, showing):
        rig = showing
        rig.press((Kind.DIGIT, 0), Kind.CONFIRM)
        assert rig.app.bible_ref == Reference(JUAN, 3, 1, 1)
        assert "Mínimo 1" in rig.message

    def test_left_and_right_change_chapter(self, showing):
        rig = showing
        rig.press(Kind.SEEK_FWD)
        assert rig.app.bible_ref == Reference(JUAN, 4, 1, 1)
        rig.press(Kind.SEEK_BACK, Kind.SEEK_BACK)
        assert rig.app.bible_ref == Reference(JUAN, 2, 1, 1)

    def test_play_does_nothing_here(self, showing):
        rig = showing
        rig.press(Kind.PLAY_PAUSE)
        assert not rig.player.active
        assert rig.app.mode is Mode.BIBLE_SHOW

    def test_star_on_a_single_verse_leaves_and_restores_the_screensaver(self, showing):
        rig = showing
        rig.player.showing_idle = False
        rig.press(Kind.STAR)
        assert rig.app.mode is Mode.BIBLE_PICK
        assert rig.player.showing_idle

    def test_all_the_way_home(self, showing):
        rig = showing
        rig.press(Kind.STAR, Kind.STAR, Kind.STAR)
        assert rig.app.mode is Mode.SELECT

    def test_the_panel_shows_the_reference_and_the_first_words(self, showing):
        vm = showing.tick()
        assert vm.status_left == "BIBLIA"
        assert vm.title == "Juan 3:2"
        assert vm.subtitle.startswith("Juan 3:2 palabra")
        assert vm.status_right == "6 vers."
        assert vm.hint == "* quita · # añade", "the keypad's own order"

    def test_a_long_reference_uses_the_abbreviation(self, rig):
        open_bible(rig)
        rig.press((Kind.DIGIT, 8), (Kind.DIGIT, 3), (Kind.DIGIT, 7), Kind.PUSH)   # Tes...
        assert rig.app.pick_book == 51                                          # 1 Tesalonicenses
        rig.press(Kind.PUSH, Kind.PUSH)
        vm = rig.press(Kind.CONFIRM, Kind.CONFIRM)
        assert vm.title == "1 Ts 1:1-3"

    def test_the_hold_to_power_off_still_works_on_the_slide(self, showing):
        rig = showing
        rig.press(Kind.PUSH)
        for _ in range(70):
            rig.clock.advance(0.05)
            rig.press(Kind.PUSH_HELD)
        assert rig.app.shutdown_requested


class TestLeavingForAHymn:
    def test_a_hymn_drops_a_slide_still_drawing(self, rig):
        """A slide landing after the hymn sets the player back to "a still is
        up", and the next tick reads that as the hymn having finished."""
        open_bible(rig)
        rig.press((Kind.DIGIT, 5), (Kind.DIGIT, 8), (Kind.DIGIT, 2), (Kind.DIGIT, 6), Kind.PUSH)
        rig.press((Kind.DIGIT, 3), Kind.PUSH, (Kind.DIGIT, 2), Kind.PUSH)
        assert rig.app.mode is Mode.BIBLE_SHOW
        rig.press(Kind.STAR, Kind.STAR)                  # picker, then the menu
        assert rig.app.mode is Mode.MENU
        rig.press(Kind.STAR)                             # home
        rig.slides.cancelled = 0
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        assert rig.player.active
        assert rig.slides.cancelled == 1
