"""The 66 books of the Bible, in order, as the RVR1960 names them.

Standard library only: tools/build_bible.py imports this table from outside
the app's virtualenv, so it must not pull Pillow or anything else in.

Each row is (name, short name, chapter count). The short name is the usual
RVR1960 abbreviation, for the panel when the full name and a reference will
not share 128 px. The chapter count is here rather than in the data so the
pick screen can bound the wheel before a book has been loaded — and so the
converter can check the downloaded file against something.
"""

import unicodedata

BOOKS: list[tuple[str, str, int]] = [
    ("Génesis", "Gn", 50), ("Éxodo", "Éx", 40), ("Levítico", "Lv", 27),
    ("Números", "Nm", 36), ("Deuteronomio", "Dt", 34), ("Josué", "Jos", 24),
    ("Jueces", "Jue", 21), ("Rut", "Rt", 4), ("1 Samuel", "1 S", 31),
    ("2 Samuel", "2 S", 24), ("1 Reyes", "1 R", 22), ("2 Reyes", "2 R", 25),
    ("1 Crónicas", "1 Cr", 29), ("2 Crónicas", "2 Cr", 36), ("Esdras", "Esd", 10),
    ("Nehemías", "Neh", 13), ("Ester", "Est", 10), ("Job", "Job", 42),
    ("Salmos", "Sal", 150), ("Proverbios", "Pr", 31), ("Eclesiastés", "Ec", 12),
    ("Cantares", "Cnt", 8), ("Isaías", "Is", 66), ("Jeremías", "Jer", 52),
    ("Lamentaciones", "Lm", 5), ("Ezequiel", "Ez", 48), ("Daniel", "Dn", 12),
    ("Oseas", "Os", 14), ("Joel", "Jl", 3), ("Amós", "Am", 9),
    ("Abdías", "Abd", 1), ("Jonás", "Jon", 4), ("Miqueas", "Mi", 7),
    ("Nahúm", "Nah", 3), ("Habacuc", "Hab", 3), ("Sofonías", "Sof", 3),
    ("Hageo", "Hag", 2), ("Zacarías", "Zac", 14), ("Malaquías", "Mal", 4),
    ("Mateo", "Mt", 28), ("Marcos", "Mr", 16), ("Lucas", "Lc", 24),
    ("Juan", "Jn", 21), ("Hechos", "Hch", 28), ("Romanos", "Ro", 16),
    ("1 Corintios", "1 Co", 16), ("2 Corintios", "2 Co", 13), ("Gálatas", "Gá", 6),
    ("Efesios", "Ef", 6), ("Filipenses", "Fil", 4), ("Colosenses", "Col", 4),
    ("1 Tesalonicenses", "1 Ts", 5), ("2 Tesalonicenses", "2 Ts", 3),
    ("1 Timoteo", "1 Ti", 6), ("2 Timoteo", "2 Ti", 4), ("Tito", "Tit", 3),
    ("Filemón", "Flm", 1), ("Hebreos", "He", 13), ("Santiago", "Stg", 5),
    ("1 Pedro", "1 P", 5), ("2 Pedro", "2 P", 3), ("1 Juan", "1 Jn", 5),
    ("2 Juan", "2 Jn", 1), ("3 Juan", "3 Jn", 1), ("Judas", "Jud", 1),
    ("Apocalipsis", "Ap", 22),
]

VERSION = "RVR1960"
# What a complete RVR1960 holds. English Bibles count 31,102; the Reina-Valera
# numbers a few passages differently (3 Juan runs to 15, for one) and lands
# two higher. The converter compares against this.
CANONICAL_VERSES = 31104


def fold(name: str) -> str:
    """A book name as a lookup key: lower case, no accents, no punctuation,
    no spaces — so "S. Mateo", "S.Juan" and "Mateo" from a downloaded file
    all land on the row they mean."""
    stripped = unicodedata.normalize("NFD", name.lower())
    letters = "".join(c for c in stripped if c.isalnum())
    # "S." / "San" prefixes on the gospels, as some sources print them
    for prefix in ("san", "s"):
        if letters.startswith(prefix) and letters[len(prefix):] in _GOSPELS:
            return letters[len(prefix):]
    return letters


_GOSPELS = {"mateo", "marcos", "lucas", "juan"}

BY_KEY: dict[str, int] = {fold(name): i for i, (name, _, _) in enumerate(BOOKS)}
