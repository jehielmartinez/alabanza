"""The text, the passage and the slide — docs/BIBLE.md, off the device.

Nothing here needs the real RVR1960: the canon's shape comes from books.py
and the words are placeholders. The converter is tested on a tiny source in
the shape of the real download, including the two defects it has to fix.
"""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from alabanza.bible import (
    MARGIN_X, MARGIN_Y, MAX_SIZE, MIN_SIZE, H, W,
    Bible, Reference, Slides, _layout, best_size, fits, render, search_books,
)
from alabanza.books import BOOKS, BY_KEY, CANONICAL_VERSES, fold

from conftest import FakePlayer, make_bible

JUAN = next(i for i, (n, _, _) in enumerate(BOOKS) if n == "Juan")
SALMOS = next(i for i, (n, _, _) in enumerate(BOOKS) if n == "Salmos")
GENESIS, APOCALIPSIS = 0, len(BOOKS) - 1


class TestTheCanon:
    def test_sixty_six_books_in_order(self):
        assert len(BOOKS) == 66
        assert BOOKS[0][0] == "Génesis" and BOOKS[-1][0] == "Apocalipsis"
        assert BOOKS[38][0] == "Malaquías" and BOOKS[39][0] == "Mateo"

    def test_the_chapter_counts_add_up(self):
        assert sum(chapters for _, _, chapters in BOOKS) == 1189

    def test_the_gospels_fold_from_the_sources_spellings(self):
        """The download says "S. Mateo" and "S.Juan"; the app says Mateo and
        Juan, and the epistles of John must not be swept up with them."""
        assert BY_KEY[fold("S. Mateo")] == BY_KEY[fold("Mateo")]
        assert BY_KEY[fold("S.Juan")] == JUAN
        assert BY_KEY[fold("1 Juan")] != JUAN
        assert BY_KEY[fold("Éxodo")] == 1

    def test_short_names_fit_a_reference_on_the_panel(self):
        for _, short, _ in BOOKS:
            assert len(short) <= 4


class TestTheText:
    def test_nothing_on_the_card_means_not_available(self, tmp_path):
        assert not Bible(tmp_path).available
        assert not Bible().available

    def test_a_half_written_card_is_not_available_either(self, tmp_path):
        (tmp_path / "index.json").write_text(json.dumps({"books": [{"file": "x"}]}))
        assert not Bible(tmp_path).available

    def test_books_load_from_the_files_the_index_names(self, tmp_path):
        files = [{"file": f"{i:02d}.json"} for i in range(len(BOOKS))]
        (tmp_path / "index.json").write_text(json.dumps({"books": files}))
        (tmp_path / f"{JUAN:02d}.json").write_text(
            json.dumps([["En el principio era el Verbo"]]))
        b = Bible(tmp_path)
        assert b.available
        assert b.text(JUAN, 1, 1) == "En el principio era el Verbo"
        assert b.verses(JUAN, 1) == 1
        assert b.verses(JUAN, 2) == 0            # not in the file
        assert b.text(GENESIS, 1, 1) == ""        # file missing: empty, no crash


class TestMovingThroughThePassage:
    @pytest.fixture
    def b(self):
        return make_bible(verses_per_chapter=5)

    def test_the_wheel_moves_the_whole_range(self, b):
        ref = Reference(JUAN, 3, 2, 3)
        assert b.step(ref, +1) == Reference(JUAN, 3, 3, 4)
        assert b.step(ref, -1) == Reference(JUAN, 3, 1, 2)

    def test_past_the_chapter_it_goes_on_into_the_next(self, b):
        assert b.step(Reference(JUAN, 3, 4, 5), +1) == Reference(JUAN, 4, 1, 2)
        assert b.step(Reference(JUAN, 4, 1, 2), -1) == Reference(JUAN, 3, 4, 5)

    def test_past_the_book_it_goes_on_into_the_next(self, b):
        assert b.step(Reference(JUAN, 21, 5, 5), +1) == Reference(JUAN + 1, 1, 1, 1)

    def test_the_bible_wraps_like_the_hymn_list(self, b):
        assert b.step(Reference(APOCALIPSIS, 22, 5, 5), +1) == Reference(GENESIS, 1, 1, 1)
        assert b.step(Reference(GENESIS, 1, 1, 1), -1) == Reference(APOCALIPSIS, 22, 5, 5)

    def test_extend_stops_at_the_chapters_end(self, b):
        assert b.extend(Reference(JUAN, 3, 4, 4)) == Reference(JUAN, 3, 4, 5)
        assert b.extend(Reference(JUAN, 3, 4, 5)) == Reference(JUAN, 3, 4, 5)

    def test_shrink_stops_at_a_single_verse(self, b):
        assert b.shrink(Reference(JUAN, 3, 1, 3)) == Reference(JUAN, 3, 1, 2)
        assert b.shrink(Reference(JUAN, 3, 1, 1)) == Reference(JUAN, 3, 1, 1)

    def test_chapters_step_from_verse_one_and_cross_books(self, b):
        assert b.chapter_step(Reference(JUAN, 3, 2, 4), +1) == Reference(JUAN, 4, 1, 1)
        assert b.chapter_step(Reference(JUAN, 1, 2, 2), -1) == Reference(JUAN - 1, 24, 1, 1)

    def test_jump_is_a_single_verse_kept_inside_the_chapter(self, b):
        assert b.jump(Reference(JUAN, 3, 1, 3), 4) == Reference(JUAN, 3, 4, 4)
        assert b.jump(Reference(JUAN, 3, 1, 3), 99) == Reference(JUAN, 3, 5, 5)
        assert b.jump(Reference(JUAN, 3, 1, 3), 0) == Reference(JUAN, 3, 1, 1)

    def test_clamp_makes_any_reference_real(self, b):
        assert b.clamp(Reference(JUAN, 99, 99, 99)) == Reference(JUAN, 21, 5, 5)
        assert b.clamp(Reference(JUAN, 3, 4, 2)) == Reference(JUAN, 3, 4, 4)

    def test_labels(self):
        assert Reference(JUAN, 3, 16, 16).label == "Juan 3:16"
        assert Reference(JUAN, 3, 16, 18).label == "Juan 3:16-18"
        assert Reference(51, 5, 16, 18).label == "1 Tesalonicenses 5:16-18"
        assert Reference(51, 5, 16, 18).short_label == "1 Ts 5:16-18"


class TestFindingABook:
    def test_predictive_t9_one_press_per_letter(self):
        names = [BOOKS[i][0] for i in search_books("5826")]        # Juan
        assert names == ["Juan", "1 Juan", "2 Juan", "3 Juan"]

    def test_it_narrows_as_you_type(self):
        assert len(search_books("7")) > len(search_books("72"))     # S… then Sa…
        assert BOOKS[search_books("725")[0]][0] == "Salmos"

    def test_accents_fold(self):
        assert GENESIS in search_books("436")                        # Gén

    def test_nothing_typed_lists_all_sixty_six(self):
        assert search_books("") == list(range(66))


class TestTheSlide:
    @pytest.fixture
    def b(self):
        return make_bible(verses_per_chapter=8)

    def test_it_is_the_size_the_projector_gets(self, b):
        image = render(b, Reference(JUAN, 3, 16, 16))
        assert image.size == (W, H)
        assert image.mode == "RGB"

    def test_white_on_black_and_nothing_else(self, b):
        image = render(b, Reference(JUAN, 3, 1, 1))
        colours = {c for _, c in image.getcolors(1 << 20)}
        assert (0, 0, 0) in colours and (255, 255, 255) in colours
        # anti-aliasing greys only: every pixel is neutral
        assert all(r == g == b_ for r, g, b_ in colours)

    def test_the_margins_stay_clear(self, b):
        image = render(b, Reference(JUAN, 3, 1, 4))
        px = image.load()
        for x in range(W):
            for y in list(range(0, MARGIN_Y)) + list(range(H - 8, H)):
                assert px[x, y] == (0, 0, 0), f"ink at {x},{y}"
        for y in range(H):
            for x in list(range(0, MARGIN_X)) + list(range(W - MARGIN_X, W)):
                assert px[x, y] == (0, 0, 0), f"ink at {x},{y}"

    def test_a_short_passage_gets_big_type_and_a_long_one_small(self, b):
        one = _layout(b, Reference(JUAN, 3, 1, 1), MAX_SIZE)
        assert one is not None, "a single verse fits at the largest size"
        assert _layout(b, Reference(JUAN, 3, 1, 8), MAX_SIZE) is None
        assert fits(b, Reference(JUAN, 3, 1, 4))

    def test_the_size_search_finds_what_a_linear_one_would(self, b):
        for last in range(1, 9):
            ref = Reference(JUAN, 3, 1, last)
            linear = next((s for s in range(MAX_SIZE, MIN_SIZE - 1, -2)
                           if _layout(b, ref, s) is not None), None)
            assert best_size(b, ref) == linear, ref

    def test_words_are_never_split(self, b):
        runs = _layout(b, Reference(JUAN, 3, 1, 3), MIN_SIZE)
        words = " ".join(r.text for r in runs if r.size == MIN_SIZE).split()
        expected = " ".join(b.text(JUAN, 3, v) for v in (1, 2, 3)).split()
        assert words == expected

    def test_the_verse_numbers_are_there_in_grey(self, b):
        runs = _layout(b, Reference(JUAN, 3, 2, 3), MIN_SIZE)
        numbers = [r.text for r in runs if r.size < MIN_SIZE]
        assert numbers == ["2", "3"]

    def test_a_passage_that_cannot_fit_still_renders(self):
        long = Bible(data={JUAN: [["palabra " * 200] * 10]})
        assert not fits(long, Reference(JUAN, 1, 1, 10))
        image = render(long, Reference(JUAN, 1, 1, 10))
        assert image.size == (W, H)


class TestTheWorker:
    def test_it_writes_a_file_and_hands_it_to_the_player(self, tmp_path):
        player = FakePlayer()
        slides = Slides(player, make_bible(), directory=tmp_path, threaded=False)
        slides.show(Reference(JUAN, 3, 16, 16))
        assert player.images == [tmp_path / "verse-1.bmp"]
        assert Image.open(player.images[0]).size == (W, H)
        assert not (tmp_path / "verse.tmp").exists(), "renamed into place"

    def test_consecutive_slides_alternate_names(self, tmp_path):
        player = FakePlayer()
        slides = Slides(player, make_bible(), directory=tmp_path, threaded=False)
        slides.show(Reference(JUAN, 3, 16, 16))
        slides.show(Reference(JUAN, 3, 17, 17))
        assert [p.name for p in player.images] == ["verse-1.bmp", "verse-0.bmp"]

    def test_on_a_thread_the_newest_request_wins(self, tmp_path):
        player = FakePlayer()
        slides = Slides(player, make_bible(), directory=tmp_path)
        try:
            for verse in range(1, 5):
                slides.show(Reference(JUAN, 3, verse, verse))
            deadline = __import__("time").monotonic() + 10
            while not player.images and __import__("time").monotonic() < deadline:
                __import__("time").sleep(0.01)
            slides.close()
        finally:
            slides.close()
        assert slides.last_error is None
        assert player.images, "nothing was rendered"
        assert len(player.images) < 4, "the ones the wheel passed were skipped"


class TestTheConverter:
    """tools/build_bible.py, on a source shaped like the real download."""

    @pytest.fixture
    def build(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
        import build_bible
        return build_bible

    def source(self):
        raw = {"lang": "SPAN"}
        for name, _, chapters in BOOKS:
            raw[name] = {str(c): {"1": "Uno. ", "2": "Dos "} for c in range(1, chapters + 1)}
        # the source's own spellings, and its glued poetry
        raw["S.Juan"] = raw.pop("Juan")
        raw["S. Mateo"] = raw.pop("Mateo")
        raw["Salmos"]["23"]["2"] = "me hará descansar;Junto a aguas de reposo.  "
        return raw

    def test_it_normalises_names_order_and_text(self, build):
        books, problems = build.convert(self.source())
        assert problems == []
        assert len(books) == 66
        assert books[JUAN][2] == ["Uno.", "Dos"]
        assert books[SALMOS][22][1] == "me hará descansar; Junto a aguas de reposo."

    def test_it_reports_what_is_wrong_with_the_source(self, build):
        raw = self.source()
        del raw["Rut"]
        raw["Tobías"] = {"1": {"1": "x"}}
        raw["Judas"]["1"] = {"1": "a", "3": "c"}
        _, problems = build.convert(raw)
        assert any("missing book: Rut" in p for p in problems)
        assert any("Tobías" in p for p in problems)
        assert any("Judas 1" in p for p in problems)

    def test_what_it_writes_is_what_the_app_reads(self, build, tmp_path):
        books, _ = build.convert(self.source())
        build.write(books, tmp_path)
        b = Bible(tmp_path)
        assert b.available
        assert b.text(JUAN, 3, 1) == "Uno."
        assert b.verses(APOCALIPSIS, 22) == 2
        assert sorted(p.name for p in tmp_path.glob("*.json"))[:2] == [
            "01-genesis.json", "02-exodo.json"]

    def test_the_canonical_count_is_the_rvr1960s(self):
        assert CANONICAL_VERSES == 31104
