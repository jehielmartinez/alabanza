"""Playback engine: a thin wrapper around libmpv.

mpv gives us everything the spec asks for: video+audio or audio-only,
seeking, pause, and pitch-preserved speed (audio-pitch-correction is on by
default, using scaletempo2).
"""

import ctypes.util
import sys
from pathlib import Path

# macOS dev machines: Homebrew's libmpv lives outside ctypes' search path.
if sys.platform == "darwin":
    _brew_lib = Path("/opt/homebrew/lib/libmpv.dylib")
    if _brew_lib.exists():
        _orig_find = ctypes.util.find_library
        ctypes.util.find_library = (
            lambda name: str(_brew_lib) if name == "mpv" else _orig_find(name)
        )

import mpv  # noqa: E402

SPEED_MIN, SPEED_MAX, SPEED_STEP = 0.75, 1.25, 0.05
SEEK_STEP_SECONDS = 10


class Player:
    def __init__(self, video: bool = True):
        self._mpv = mpv.MPV(
            vid="auto" if video else "no",
            osc=False,
            force_window=False,
            keep_open=False,
            log_handler=None,
        )
        self._mpv.volume = 80

    # -- lifecycle -----------------------------------------------------
    def play(self, path: Path) -> None:
        self._mpv.speed = 1.0  # spec: speed resets per hymn
        self._mpv.play(str(path))
        self._mpv.pause = False

    def toggle_pause(self) -> None:
        if self.active:
            self._mpv.pause = not self._mpv.pause

    def stop(self) -> None:
        self._mpv.stop()

    def shutdown(self) -> None:
        self._mpv.terminate()

    # -- state ---------------------------------------------------------
    @property
    def active(self) -> bool:
        """A file is loaded (playing or paused)."""
        return self._mpv.filename is not None

    @property
    def paused(self) -> bool:
        return bool(self._mpv.pause)

    @property
    def position(self) -> float:
        return self._mpv.time_pos or 0.0

    @property
    def duration(self) -> float:
        return self._mpv.duration or 0.0

    # -- controls ------------------------------------------------------
    def seek(self, seconds: float) -> None:
        if self.active:
            self._mpv.seek(seconds, reference="relative")

    def nudge_speed(self, direction: int) -> float:
        new = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + direction * SPEED_STEP)), 2)
        self._mpv.speed = new
        return new

    @property
    def speed(self) -> float:
        return float(self._mpv.speed)

    @property
    def volume(self) -> int:
        return int(self._mpv.volume or 0)

    def nudge_volume(self, direction: int) -> int:
        new = min(100, max(0, self.volume + direction * 2))
        self._mpv.volume = new
        return new
