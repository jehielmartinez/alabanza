"""The Bible screens, driven the way the panel drives them — docs/BIBLE.md.

Same nineteen inputs as everything else. Psalm 23 from the menu is five
presses; from then on the wheel follows the reading, # puts one more verse
on the wall, * takes one off.
"""

import pytest

from alabanza.app import Mode
from alabanza.bible import Reference
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

    def test_the_dpad_does_the_same(self, showing):
        rig = showing
        rig.press(Kind.DOWN)
        assert rig.app.bible_ref == Reference(JUAN, 3, 3, 3)
        rig.press(Kind.UP)
        assert rig.app.bible_ref == Reference(JUAN, 3, 2, 2)

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
        assert vm.hint == "# añade · * quita"

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
