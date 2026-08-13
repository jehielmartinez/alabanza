"""Hymn library index: number -> (title, file).

Phase 0 builds the index by parsing filenames like
"005 Al Cielo Voy [2-X6y9xwV9Q].mp4". On the final device the index is
built once at provisioning and this scan never runs at runtime.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_T9 = {c: d for d, letters in {
    "2": "abc", "3": "def", "4": "ghi", "5": "jkl",
    "6": "mno", "7": "pqrs", "8": "tuv", "9": "wxyz",
}.items() for c in letters}


def _t9_digits(word: str) -> str:
    """'Cielo' -> '24356'. Accents folded (á->a, ñ->n); non-letters dropped."""
    folded = unicodedata.normalize("NFD", word.lower())
    return "".join(_T9[c] for c in folded if c in _T9)

# "005 Al Cielo Voy [2-X6y9xwV9Q].mp4" -> (5, "Al Cielo Voy")
_FILENAME = re.compile(
    r"^(?P<num>\d{1,3})[\s\-_.]*(?P<title>.*?)(?:\s*\[[\w-]{11}\])?\.mp4$"
)


@dataclass(frozen=True)
class Hymn:
    number: int
    title: str
    path: Path


@dataclass
class Library:
    hymns: dict[int, Hymn]
    warnings: list[str]

    @property
    def numbers(self) -> list[int]:
        return sorted(self.hymns)

    def get(self, number: int) -> Hymn | None:
        return self.hymns.get(number)

    def neighbor(self, number: int, step: int) -> int:
        """Next/previous existing hymn number from `number` (for browsing)."""
        nums = self.numbers
        if not nums:
            return number
        if number not in self.hymns:
            nums_after = [n for n in nums if (n > number if step > 0 else n < number)]
            return (min(nums_after) if step > 0 else max(nums_after)) if nums_after else nums[0 if step > 0 else -1]
        i = nums.index(number) + step
        return nums[max(0, min(i, len(nums) - 1))]

    def search_t9(self, query: str) -> list[Hymn]:
        """Hymns where any title word starts with the T9 digit sequence."""
        if not query:
            return []
        hymns = (self.hymns[n] for n in self.numbers)
        return [
            h for h in hymns
            if any(_t9_digits(word).startswith(query) for word in h.title.split())
        ]


def scan(directory: Path) -> Library:
    """Load the library: manifest.json if present (the provisioned form),
    else fall back to parsing filenames (raw downloads, dev only)."""
    manifest = directory / "manifest.json"
    if manifest.exists():
        return _load_manifest(manifest)
    return _scan_filenames(directory)


def _load_manifest(manifest_path: Path) -> Library:
    import json

    hymns: dict[int, Hymn] = {}
    warnings: list[str] = []
    for entry in json.loads(manifest_path.read_text()):
        path = manifest_path.parent / entry["file"]
        if not path.exists():
            warnings.append(f"manifest file missing: {entry['file']}")
            continue
        hymns[entry["number"]] = Hymn(entry["number"], entry["title"], path)
    return Library(hymns, warnings)


def _scan_filenames(directory: Path) -> Library:
    hymns: dict[int, Hymn] = {}
    warnings: list[str] = []
    if not directory.is_dir():
        return Library({}, [f"library dir not found: {directory}"])
    for path in sorted(directory.glob("*.mp4")):
        m = _FILENAME.match(path.name)
        if not m:
            warnings.append(f"unparseable filename: {path.name}")
            continue
        number = int(m.group("num"))
        title = m.group("title").strip() or f"Himno {number}"
        if number in hymns:
            warnings.append(f"duplicate hymn {number}: kept {hymns[number].path.name}, ignored {path.name}")
            continue
        hymns[number] = Hymn(number, title, path)
    return Library(hymns, warnings)
