# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build the canonical Alabanza library from the raw YouTube downloads.

    uv run provision_library.py            # downloads/ -> library/
    uv run provision_library.py --check    # report only, write nothing

Takes tools/downloads/*.mp4 ("005 Al Cielo Voy [id].mp4") and produces:

    tools/library/NNN - Title.mp4     one file per hymn (hardlink, no copy)
    tools/library/manifest.json       the runtime index: number, title, file,
                                      duration, source YouTube id
    tools/library/report.txt          duplicates resolved, missing numbers

Duplicate hymn numbers (two uploads of the same hymn) are resolved by
preferring, in order: an entry in overrides.txt ("238 <youtube-id>" per
line), then the longer video, then the larger file.

Idempotent: re-running rebuilds library/ from scratch.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = TOOLS_DIR / "downloads"
LIBRARY_DIR = TOOLS_DIR / "library"
OVERRIDES_FILE = TOOLS_DIR / "overrides.txt"
EXPECTED_RANGE = range(1, 518)  # hymnal is 1..517

_FILENAME = re.compile(
    r"^(?P<num>\d{1,3})[\s\-_.]*(?P<title>.*?)\s*\[(?P<ytid>[\w-]{11})\]\.mp4$"
)


@dataclass
class Source:
    number: int
    title: str
    ytid: str
    path: Path
    duration: float = 0.0

    @property
    def size(self) -> int:
        return self.path.stat().st_size


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def load_overrides() -> dict[int, str]:
    overrides: dict[int, str] = {}
    if OVERRIDES_FILE.exists():
        for line in OVERRIDES_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                num, ytid = line.split(maxsplit=1)
                overrides[int(num)] = ytid.strip()
    return overrides


# trailing uploader notes that survive outside parentheses,
# e.g. "El Amigo Más Fiel (pista) Tono original de HCE"
_TRAILING_NOTES = re.compile(
    r"(?i)[\s.,;-]*(tono original.*|hermoso himno\.?|¡?qu[eé] precioso himno!*|pista)$"
)


def clean_title(raw: str) -> str:
    """Strip uploader annotations: '(Pista)', '(Tono original de HCE)',
    '(precioso himno)', trailing notes, trailing periods."""
    title = raw.replace("？", "?")
    title = re.sub(r"\s*\([^)]*\)", "", title)   # all parentheticals are annotations
    title = _TRAILING_NOTES.sub("", title)
    title = re.sub(r"\s+", " ", title).strip()
    title = title.rstrip(".,;: ").strip()
    return title or "Sin titulo"


def collect_sources() -> tuple[list[Source], list[str]]:
    sources, problems = [], []
    for path in sorted(DOWNLOAD_DIR.glob("*.mp4")):
        m = _FILENAME.match(path.name)
        if not m:
            problems.append(f"unparseable filename, skipped: {path.name}")
            continue
        sources.append(Source(
            number=int(m.group("num")),
            title=clean_title(m.group("title")),
            ytid=m.group("ytid"),
            path=path,
        ))
    return sources, problems


def resolve_duplicates(
    sources: list[Source], overrides: dict[int, str]
) -> tuple[dict[int, Source], list[str]]:
    by_number: dict[int, list[Source]] = {}
    for src in sources:
        by_number.setdefault(src.number, []).append(src)

    chosen: dict[int, Source] = {}
    notes: list[str] = []
    for number, candidates in sorted(by_number.items()):
        if len(candidates) == 1:
            chosen[number] = candidates[0]
            continue
        for c in candidates:
            c.duration = probe_duration(c.path)
        pick = None
        if number in overrides:
            pick = next((c for c in candidates if c.ytid == overrides[number]), None)
            if pick is None:
                notes.append(f"hymn {number}: override id {overrides[number]} "
                             "not found among candidates; falling back")
        if pick is None:
            pick = max(candidates, key=lambda c: (c.duration, c.size))
        chosen[number] = pick
        for c in candidates:
            mark = "KEPT   " if c is pick else "dropped"
            notes.append(
                f"hymn {number}: {mark} [{c.ytid}] {c.duration:6.1f}s "
                f"{c.size / 1e6:5.1f}MB  {c.path.name}"
            )
    return chosen, notes


def build_library(chosen: dict[int, Source], check_only: bool) -> list[dict]:
    if not check_only:
        if LIBRARY_DIR.exists():
            shutil.rmtree(LIBRARY_DIR)
        LIBRARY_DIR.mkdir()
    manifest = []
    for number, src in sorted(chosen.items()):
        filename = f"{number:03d} - {src.title}.mp4"
        if not check_only:
            target = LIBRARY_DIR / filename
            try:
                target.hardlink_to(src.path)
            except OSError:
                shutil.copy2(src.path, target)
        if not src.duration:
            src.duration = probe_duration(src.path)
        manifest.append({
            "number": number,
            "title": src.title,
            "file": filename,
            "duration": round(src.duration, 1),
            "youtube_id": src.ytid,
        })
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report only; write nothing")
    args = parser.parse_args()

    if not DOWNLOAD_DIR.is_dir():
        print(f"downloads dir not found: {DOWNLOAD_DIR}")
        return 1

    sources, problems = collect_sources()
    chosen, dup_notes = resolve_duplicates(sources, load_overrides())
    missing = [n for n in EXPECTED_RANGE if n not in chosen]
    unexpected = [n for n in chosen if n not in EXPECTED_RANGE]

    print(f"source files:   {len(sources)}")
    print(f"unique hymns:   {len(chosen)}")
    print(f"missing:        {missing or 'none'}")
    if unexpected:
        print(f"outside 1-517:  {unexpected}")

    manifest = build_library(chosen, args.check)

    report = ["= Alabanza provisioning report ="]
    report.append(f"{len(sources)} source files -> {len(chosen)} hymns")
    report.append(f"missing numbers: {missing or 'none'}")
    if unexpected:
        report.append(f"numbers outside 1-517: {unexpected}")
    report += ["", "= duplicates =", *dup_notes] if dup_notes else []
    report += ["", "= problems =", *problems] if problems else []
    report_text = "\n".join(report) + "\n"

    if args.check:
        print("\n" + report_text)
        print("(check mode: nothing written)")
    else:
        (LIBRARY_DIR / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1))
        (LIBRARY_DIR / "report.txt").write_text(report_text)
        total_gb = sum(s.size for s in chosen.values()) / 1e9
        print(f"library:        {LIBRARY_DIR} ({total_gb:.1f} GB, hardlinked)")
        print(f"manifest:       {len(manifest)} entries")
        print("report:         library/report.txt")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
