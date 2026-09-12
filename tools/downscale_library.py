# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Make a 480p copy of the provisioned library for the original Pi Zero W.

    uv run downscale_library.py             # library/ -> library-480/
    uv run downscale_library.py --check     # report what would be done
    uv run downscale_library.py -j 4        # parallel encodes (default: 4)

The Zero W has one ARM11 core. Its H.264 block decodes the 720p library
fine, but every decoded frame still has to be moved and converted by that
core, and at 720p it cannot keep up. 480p is a third of the pixels, and
lyrics videos are text on a still background -- nothing is lost that a
projector would show.

Output is a drop-in library: same filenames, same manifest.json, so it works
with `alabanza --library tools/library-480` and nothing else changes.
Durations in the manifest are unchanged because the audio is copied, not
re-encoded (AAC 128 kbps throughout; re-encoding would only lose quality).

Encoding: H.264 Main profile, level 3.1, CRF 22, yuv420p, faststart. Main
rather than High because the stream is small either way and Main is the
safer bet for an old decoder; level 3.1 is generous for 480p. Files already
at or below 480 high are remuxed with the video stream copied.

Resumable: an existing output is skipped, and each file is written to a
.part name and renamed only when ffmpeg exits 0, so a killed run never
leaves a truncated hymn that plays for thirty seconds and stops.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SOURCE_DIR = TOOLS_DIR / "library"
TARGET_DIR = TOOLS_DIR / "library-480"
HEIGHT = 480


def probe_height(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return int(out) if out else 0


def encode(src: Path, dst: Path) -> tuple[Path, str]:
    """One hymn. Returns (src, outcome) for the progress line."""
    if dst.exists():
        return src, "skip"
    part = dst.with_name(dst.name + ".part.mp4")
    height = probe_height(src)
    if height and height <= HEIGHT:
        video = ["-c:v", "copy"]
        outcome = "copied"
    else:
        # -2 keeps the aspect ratio and rounds the width to an even number,
        # which yuv420p requires; widths in this library vary per clip.
        video = ["-vf", f"scale=-2:{HEIGHT}", "-c:v", "libx264",
                 "-profile:v", "main", "-level", "3.1", "-preset", "medium",
                 "-crf", "22", "-pix_fmt", "yuv420p", "-threads", "3"]
        outcome = "encoded"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", str(src), *video, "-c:a", "copy",
           "-movflags", "+faststart", str(part)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        part.unlink(missing_ok=True)
        return src, f"FAILED: {result.stderr.strip().splitlines()[-1:] or result.returncode}"
    part.rename(dst)
    return src, outcome


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="parallel encodes")
    args = ap.parse_args()

    manifest = SOURCE_DIR / "manifest.json"
    if not manifest.exists():
        print(f"no {manifest} — run provision_library.py first", file=sys.stderr)
        return 1
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} not found — brew install ffmpeg", file=sys.stderr)
            return 1

    entries = json.loads(manifest.read_text())
    sources = [SOURCE_DIR / e["file"] for e in entries]
    missing = [s.name for s in sources if not s.exists()]
    if missing:
        print(f"{len(missing)} manifest files missing from {SOURCE_DIR}: {missing[:3]}...",
              file=sys.stderr)
        return 1

    todo = [s for s in sources if not (TARGET_DIR / s.name).exists()]
    print(f"{len(sources)} hymns, {len(sources) - len(todo)} done, {len(todo)} to go"
          f" -> {TARGET_DIR}")
    if args.check:
        return 0

    TARGET_DIR.mkdir(exist_ok=True)
    for leftover in TARGET_DIR.glob("*.part.mp4"):
        leftover.unlink()

    started = time.monotonic()
    failed = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(encode, s, TARGET_DIR / s.name) for s in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            src, outcome = fut.result()
            if outcome.startswith("FAILED"):
                failed.append(src.name)
            elapsed = time.monotonic() - started
            eta = elapsed / n * (len(todo) - n)
            print(f"[{n}/{len(todo)}] {outcome:8} {src.name}   (eta {eta / 60:.0f} min)",
                  flush=True)

    # The manifest is byte-for-byte the source one: same files, same
    # numbers, same durations. Copied last, so a half-finished run has no
    # manifest and the app refuses the folder rather than loading a gap.
    if not failed:
        shutil.copy2(manifest, TARGET_DIR / "manifest.json")
        total = sum(p.stat().st_size for p in TARGET_DIR.glob("*.mp4"))
        print(f"done: {len(sources)} hymns, {total / 1e9:.2f} GB, manifest written")
        return 0
    print(f"{len(failed)} failed, manifest NOT written: {failed}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
