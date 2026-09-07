"""Playback engine: a thin wrapper around libmpv.

mpv gives us everything the spec asks for: video+audio or audio-only,
seeking, pause, and pitch-preserved speed (audio-pitch-correction is on by
default, using scaletempo2).
"""

import ctypes.util
import os
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


def _video_options() -> dict:
    """mpv's video settings for whatever machine this is.

    On the device there is no window system at all, so video goes straight to
    DRM/KMS — which is what makes SPEC decision 8's "fullscreen video, zero
    overlays" easy rather than a fight with a compositor.

    `hwdec` has to name the decoder. mpv's own `auto` probes CUDA and Vulkan,
    finds neither on a Pi, and falls back to software without complaint; the
    Pi's H.264 block is reached through V4L2 M2M and is never tried. Measured
    on the Pi 4 bench: load 0.62 with `v4l2m2m-copy` against 1.65 without, on
    the same 720p file. The Zero 2 W has roughly a quarter of that CPU, so
    this setting is the difference between decision 16 holding and not.

    Returns nothing on a dev machine: macOS has no DRM, and a Linux desktop
    with a display server should keep mpv's own windowed defaults.
    """
    if sys.platform != "linux":
        return {}
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return {}
    if not Path("/dev/dri").exists():
        return {}
    return {"vo": "drm", "hwdec": "v4l2m2m-copy"}


class Player:
    def __init__(self, video: bool = True):
        self._mpv = mpv.MPV(
            vid="auto" if video else "no",
            osc=False,
            force_window=False,
            keep_open=False,
            log_handler=None,
            **(_video_options() if video else {}),
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

    # -- output routing ------------------------------------------------
    @property
    def audio_devices(self) -> list[tuple[str, str]]:
        """mpv's own sink list, as (name, description). audio.py matches on it."""
        try:
            return [(d["name"], d.get("description") or "")
                    for d in (self._mpv.audio_device_list or [])]
        except (AttributeError, KeyError, TypeError):
            return []

    @property
    def audio_device(self) -> str:
        return str(self._mpv.audio_device or "auto")

    @audio_device.setter
    def audio_device(self, name: str) -> None:
        """Switching while playing costs a sub-second AO reinit — acceptable,
        and only ever triggered by an explicit menu action."""
        if name and name != self.audio_device:
            self._mpv.audio_device = name

    @property
    def volume(self) -> int:
        return int(self._mpv.volume or 0)

    @volume.setter
    def volume(self, value: int) -> None:
        self._mpv.volume = max(0, min(100, value))

    def nudge_volume(self, direction: int) -> int:
        new = min(100, max(0, self.volume + direction * 2))
        self._mpv.volume = new
        return new
