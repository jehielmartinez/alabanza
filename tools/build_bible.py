# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Lay the Reina-Valera 1960 out the way the app reads it.

    uv run build_bible.py                     # download, convert, report
    uv run build_bible.py --source file.json  # convert a copy you already have
    uv run build_bible.py --check             # report only, write nothing

Takes the dscottpi/bibles JSON -- {book: {chapter: {verse: text}}} -- and
writes tools/bible/rvr1960/:

    index.json        version, and the 66 books in canonical order with
                      their file names and chapter counts
    NN-nombre.json    one per book: a list of chapters, each a list of verse
                      strings, verse 1 at index 0

The source names its books its own way ("S.Juan", "S. Mateo") and sorts them
alphabetically; this puts them in order under the names the app shows, and
strips the trailing space every verse carries. It also *checks*: chapter
counts against books.py, verse numbers for gaps and duplicates, and the
total against the 31,104 a complete RVR1960 holds -- so a defect in the download is found
here, once, and not on a projector.

The text is copyright Sociedades Bíblicas Unidas and is not in this repo:
tools/bible/ is git-ignored, like the hymn library. See docs/BIBLE.md.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent / "app"))
from alabanza.books import BOOKS, BY_KEY, CANONICAL_VERSES, VERSION, fold  # noqa: E402

OUT_DIR = TOOLS_DIR / "bible" / "rvr1960"
SOURCE_URL = ("https://raw.githubusercontent.com/dscottpi/bibles/master/"
              "RVR1960%20-%20Spanish.json")


def _slug(name: str) -> str:
    folded = unicodedata.normalize("NFD", name.lower())
    plain = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


# The source lost the line breaks of its poetry: "me hará descansar;Junto a
# aguas de reposo" is how Salmos 23:2 arrives, and 4,893 verses are like it.
# A line of a psalm always ends in punctuation and the next starts with a
# capital, so that pair is where the space goes back.
_GLUED = re.compile(r"([;,.:!?])(?=[A-ZÁÉÍÓÚÑ¿¡])")


def _clean(text: str) -> str:
    return " ".join(_GLUED.sub(r"\1 ", text).split())


def _fetch(source: str | None) -> dict:
    if source:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    print(f"downloading {SOURCE_URL}")
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def convert(raw: dict) -> tuple[list[list[list[str]]], list[str]]:
    """The 66 books in order, and every complaint about the source."""
    books: list[list[list[str]]] = [[] for _ in BOOKS]
    problems: list[str] = []
    seen: set[int] = set()
    for key, chapters in raw.items():
        if not isinstance(chapters, dict):
            continue                        # "lang": "SPAN" and the like
        index = BY_KEY.get(fold(key))
        if index is None:
            problems.append(f"unknown book in source: {key!r}")
            continue
        if index in seen:
            problems.append(f"book appears twice in source: {key!r}")
            continue
        seen.add(index)
        name, _, expected_chapters = BOOKS[index]
        numbered = sorted(((int(c), v) for c, v in chapters.items()), key=lambda cv: cv[0])
        if [c for c, _ in numbered] != list(range(1, expected_chapters + 1)):
            problems.append(f"{name}: chapters {[c for c, _ in numbered][:3]}…"
                            f" ({len(numbered)}), expected 1..{expected_chapters}")
        for chapter, verses in numbered:
            ordered = sorted(((int(v), t) for v, t in verses.items()), key=lambda vt: vt[0])
            numbers = [v for v, _ in ordered]
            if numbers != list(range(1, len(numbers) + 1)):
                problems.append(f"{name} {chapter}: verse numbers {numbers[:5]}…"
                                f" are not 1..{len(numbers)}")
            books[index].append([_clean(t) for _, t in ordered])
    for index, (name, _, _) in enumerate(BOOKS):
        if index not in seen:
            problems.append(f"missing book: {name}")
    return books, problems


def write(books: list[list[list[str]]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {"version": VERSION, "books": []}
    for i, ((name, short, chapters), text) in enumerate(zip(BOOKS, books)):
        file = f"{i + 1:02d}-{_slug(name)}.json"
        (out_dir / file).write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
        index["books"].append({"name": name, "short": short,
                               "chapters": chapters, "file": file})
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1),
                                        encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", help="a downloaded copy of the JSON")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true", help="report only")
    args = parser.parse_args()

    books, problems = convert(_fetch(args.source))
    total = sum(len(chapter) for book in books for chapter in book)
    print(f"{sum(1 for b in books if b)} books, "
          f"{sum(len(b) for b in books)} chapters, {total} verses "
          f"(canonical {CANONICAL_VERSES})")
    for problem in problems:
        print(f"  ! {problem}")
    if total != CANONICAL_VERSES:
        print(f"  ! verse total differs from canonical by {total - CANONICAL_VERSES}")
    if args.check:
        return 1 if problems else 0
    write(books, args.out)
    print(f"written to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
