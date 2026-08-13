# /// script
# requires-python = ">=3.11"
# dependencies = ["yt-dlp>=2026.1.1"]
# ///
"""Download the Alabanza hymn library from YouTube playlists.

Usage:
    uv run download_hymns.py                        # playlists.txt, cookies from Chrome
    uv run download_hymns.py --browser brave        # cookies from Brave (or safari/firefox/edge)
    uv run download_hymns.py my_lists.txt           # explicit playlist file

YouTube's bot detection requires cookies from a browser where you're signed in
to YouTube. Make sure you've visited youtube.com logged-in in that browser.
macOS may show a keychain prompt ("Safe Storage") on first run — click Allow.

Fully resumable: already-downloaded videos are recorded in downloads/archive.txt
and skipped on the next run. Just re-run until it reports everything done.
Failures are listed in downloads/failed.txt with the reason.

Output format targets the Raspberry Pi 4: H.264 (avc1) video capped at 1080p +
AAC audio in an MP4 container — the Pi 4 hardware-decodes H.264 only, so
YouTube's VP9/AV1 "best" streams are deliberately avoided.
"""

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

CONCURRENCY = 5
TOOLS_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = TOOLS_DIR / "downloads"
ARCHIVE_FILE = DOWNLOAD_DIR / "archive.txt"
FAILED_FILE = DOWNLOAD_DIR / "failed.txt"

# Pi 4 hardware decode: H.264 up to 1080p. Prefer avc1+m4a, fall back to any
# progressive MP4, never exceed 1080p.
FORMAT = (
    "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]"
    "/bestvideo[vcodec^=avc1][height<=1080]+bestaudio"
    "/best[ext=mp4][height<=1080]"
    "/best[height<=1080]"
)

archive_lock = threading.Lock()
print_lock = threading.Lock()


def say(msg: str) -> None:
    with print_lock:
        print(msg, flush=True)


def read_playlist_file(path: Path) -> list[str]:
    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def collect_videos(playlist_urls: list[str], browser: str) -> list[dict]:
    """Flat-extract every playlist and return deduplicated video entries."""
    seen: dict[str, dict] = {}
    opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "cookiesfrombrowser": (browser,),
        "remote_components": ["ejs:github"],
    }
    with YoutubeDL(opts) as ydl:
        for url in playlist_urls:
            say(f"Reading playlist: {url}")
            try:
                info = ydl.extract_info(url, download=False)
            except DownloadError as e:
                say(f"  !! could not read playlist: {e}")
                continue
            entries = info.get("entries") or [info]
            fresh = 0
            for entry in entries:
                vid = entry.get("id")
                if vid and vid not in seen:
                    seen[vid] = entry
                    fresh += 1
            say(f"  {len(entries)} videos ({fresh} new after dedup)")
    return list(seen.values())


def load_archive() -> set[str]:
    if not ARCHIVE_FILE.exists():
        return set()
    return {
        line.split()[-1]
        for line in ARCHIVE_FILE.read_text().splitlines()
        if line.strip()
    }


def mark_done(video_id: str) -> None:
    with archive_lock:
        with ARCHIVE_FILE.open("a") as f:
            f.write(f"youtube {video_id}\n")


def download_one(
    entry: dict, index: int, total: int, browser: str
) -> tuple[str, str | None]:
    """Download one video. Returns (video_id, error_or_None)."""
    vid = entry["id"]
    title = entry.get("title") or vid
    say(f"[{index}/{total}] downloading: {title}")
    opts = {
        "format": FORMAT,
        "cookiesfrombrowser": (browser,),
        "remote_components": ["ejs:github"],
        "merge_output_format": "mp4",
        "outtmpl": str(DOWNLOAD_DIR / "%(title)s [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "continuedl": True,  # resume partial .part files
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 1,  # parallelism is across videos, not fragments
    }
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
    except DownloadError as e:
        say(f"[{index}/{total}] FAILED: {title} — {e}")
        return vid, str(e)
    mark_done(vid)
    say(f"[{index}/{total}] done: {title}")
    return vid, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "playlist_file", nargs="?", default=str(TOOLS_DIR / "playlists.txt"),
        help="file with one playlist URL per line (default: playlists.txt)",
    )
    parser.add_argument(
        "--browser", default="chrome",
        choices=["chrome", "brave", "safari", "firefox", "edge"],
        help="browser to borrow YouTube cookies from — must be signed in to "
        "YouTube there (default: chrome)",
    )
    args = parser.parse_args()

    playlist_path = Path(args.playlist_file)
    if not playlist_path.exists():
        print(f"Playlist file not found: {playlist_path}")
        return 1
    playlist_urls = read_playlist_file(playlist_path)
    if not playlist_urls:
        print(f"No playlist URLs in {playlist_path} — add one URL per line.")
        return 1

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    videos = collect_videos(playlist_urls, args.browser)
    done = load_archive()
    pending = [v for v in videos if v["id"] not in done]
    say(
        f"\nTotal unique videos: {len(videos)} | already downloaded: "
        f"{len(videos) - len(pending)} | to download: {len(pending)}\n"
    )
    if not pending:
        say("Nothing to do — library is complete.")
        return 0

    failures: list[tuple[str, str, str]] = []
    total = len(pending)
    pool = ThreadPoolExecutor(max_workers=CONCURRENCY)
    try:
        futures = {
            pool.submit(download_one, entry, i, total, args.browser): entry
            for i, entry in enumerate(pending, start=1)
        }
        for future in as_completed(futures):
            entry = futures[future]
            vid, error = future.result()
            if error:
                failures.append((vid, entry.get("title") or vid, error))
        pool.shutdown(wait=True)
    except KeyboardInterrupt:
        say("\nInterrupted — finishing in-flight downloads, then stopping. "
            "Re-run to resume.")
        pool.shutdown(wait=True, cancel_futures=True)
        return 130

    say(f"\nFinished: {total - len(failures)} downloaded, {len(failures)} failed.")
    if failures:
        with FAILED_FILE.open("w") as f:
            for vid, title, error in failures:
                f.write(f"{vid}\t{title}\t{error}\n")
        say(f"Failures written to {FAILED_FILE} — re-run this script to retry them.")
        return 1
    say("All videos downloaded. Library complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
