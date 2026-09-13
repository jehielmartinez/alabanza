"""The hymn index: number -> title -> file.

Getting this wrong means an operator types 347 and hears the wrong hymn, so
the parsing edge cases in the real download filenames are pinned here.
"""

import json

from alabanza.library import scan


def write(directory, *names):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"")
    return directory


def test_parses_the_youtube_download_naming(tmp_path):
    write(tmp_path, "005 Al Cielo Voy [2-X6y9xwV9Q].mp4")
    library = scan(tmp_path)
    assert library.get(5).title == "Al Cielo Voy"
    assert not library.warnings


def test_parses_separators_and_missing_titles(tmp_path):
    write(tmp_path, "014 - Bienvenida da Jesús.mp4", "279_¡Santo!.mp4", "42.mp4")
    library = scan(tmp_path)
    assert library.get(14).title == "Bienvenida da Jesús"
    assert library.get(279).title == "¡Santo!"
    assert library.get(42).title == "Himno 42"


def test_a_duplicate_number_is_reported_not_silently_overwritten(tmp_path):
    write(tmp_path, "005 First.mp4", "005 Second.mp4")
    library = scan(tmp_path)
    assert library.get(5).title == "First"          # first one wins
    assert any("duplicate hymn 5" in w for w in library.warnings)


def test_unparseable_names_are_reported(tmp_path):
    write(tmp_path, "no number here.mp4")
    library = scan(tmp_path)
    assert not library.hymns
    assert any("unparseable" in w for w in library.warnings)


def test_a_missing_library_is_a_warning_not_a_crash(tmp_path):
    library = scan(tmp_path / "nope")
    assert library.hymns == {}
    assert library.warnings


def test_the_manifest_wins_over_filenames(tmp_path):
    write(tmp_path, "005 Whatever The File Is Called.mp4")
    (tmp_path / "manifest.json").write_text(json.dumps(
        [{"number": 5, "title": "Al Cielo Voy",
          "file": "005 Whatever The File Is Called.mp4"}]))
    assert scan(tmp_path).get(5).title == "Al Cielo Voy"


def test_a_manifest_entry_with_no_file_is_reported(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifest.json").write_text(json.dumps(
        [{"number": 5, "title": "Gone", "file": "missing.mp4"}]))
    library = scan(tmp_path)
    assert not library.hymns
    assert any("missing.mp4" in w for w in library.warnings)


class TestT9Search:
    """Digits are letters: 2=abc 3=def ... 9=wxyz, matched per word."""

    def library(self, tmp_path):
        write(tmp_path, "005 Al Cielo Voy.mp4", "014 Bienvenida da Jesús.mp4",
              "279 Santo Santo Santo.mp4")
        return scan(tmp_path)

    def test_matches_a_word_prefix(self, tmp_path):
        found = self.library(tmp_path).search_t9("2435")  # C-I-E-L
        assert [h.number for h in found] == [5]

    def test_a_short_prefix_is_ambiguous_and_more_digits_narrow_it(self, tmp_path):
        # 243 is both "Cie(lo)" and "Bie(nvenida)" — this is how T9 behaves,
        # and why the results list is scrollable
        library = self.library(tmp_path)
        assert [h.number for h in library.search_t9("243")] == [5, 14]
        assert [h.number for h in library.search_t9("2436")] == [14]

    def test_matches_any_word_not_just_the_first(self, tmp_path):
        found = self.library(tmp_path).search_t9("537")   # J-E-S
        assert [h.number for h in found] == [14]

    def test_accents_fold_so_jesus_is_reachable(self, tmp_path):
        # "Jesús" must be findable by typing plain letters
        assert self.library(tmp_path).search_t9("53787")  # J-E-S-U-S

    def test_an_empty_query_matches_nothing(self, tmp_path):
        assert self.library(tmp_path).search_t9("") == []


class TestBrowsing:
    def test_walks_to_the_next_and_previous_existing_number(self, tmp_path):
        write(tmp_path, "005 A.mp4", "014 B.mp4", "279 C.mp4")
        library = scan(tmp_path)
        assert library.neighbor(5, +1) == 14
        assert library.neighbor(14, -1) == 5

    def test_wraps_at_the_ends(self, tmp_path):
        """A knob has no end stop: after the last hymn comes the first."""
        write(tmp_path, "005 A.mp4", "014 B.mp4")
        library = scan(tmp_path)
        assert library.neighbor(14, +1) == 5
        assert library.neighbor(5, -1) == 14

    def test_lands_somewhere_sane_from_a_gap(self, tmp_path):
        write(tmp_path, "005 A.mp4", "279 C.mp4")
        library = scan(tmp_path)
        assert library.neighbor(100, +1) == 279
        assert library.neighbor(100, -1) == 5

    def test_an_empty_library_does_not_explode(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        assert scan(tmp_path).neighbor(5, +1) == 5
