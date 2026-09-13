"""Playback engine: a thin wrapper around libmpv.

mpv gives us everything the spec asks for: video+audio or audio-only,
seeking, pause, and pitch-preserved speed (audio-pitch-correction is on by
default, using scaletempo2).
"""

import ctypes.util
import os
import platform
import random
import sys
import time
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

# Shown on HDMI whenever no hymn is on screen — boot, idle and stop, per
# SPEC.md decision 8. Any number of them: one is chosen at random each time
# the screen goes idle, so the projector is not showing the same verse all
# morning. Regenerate with tools/make_screensaver.py; drop in replacements
# named screensaver*.png and they are picked up with no code change.
IDLE_DIR = Path(__file__).parent / "assets"

# mpv loads asynchronously: play() returns in ~1 ms but `filename` only appears
# ~12 ms later. Until then a hymn is starting but not yet reported as loaded,
# and app.tick() -- which runs microseconds after handle() -- would read that
# as "the hymn finished on its own". How long to keep answering `active` while
# a load is in flight, before concluding it failed.
START_GRACE = 5.0


def _idle_images(directory: Path = IDLE_DIR) -> list[Path]:
    return sorted(directory.glob("screensaver*.png"))


def _drm_device() -> str | None:
    """The DRM card with something actually plugged into it, or None.

    Card numbering is not stable across boots — the same Pi 4 had its HDMI on
    card0 one boot and card1 the next — so the card is found by asking which
    one owns a connector reporting `connected`, never by hardcoding a path.
    """
    for status in sorted(Path("/sys/class/drm").glob("card*/status")):
        try:
            if status.read_text().strip() != "connected":
                continue
        except OSError:
            continue
        card = status.parent.name.split("-", 1)[0]      # card1-HDMI-A-2 -> card1
        node = Path("/dev/dri") / card
        if node.exists():
            return str(node)
    return None


def _video_options() -> dict:
    """mpv's video settings for whatever machine this is.

    On the device there is no window system at all, so video goes straight to
    DRM/KMS — which is what makes SPEC decision 8's "fullscreen video, zero
    overlays" a configuration rather than a fight with a compositor.

    Two things have to be explicit or the appliance misbehaves:

    `hwdec` must name the decoder. mpv's `auto` probes CUDA and Vulkan, finds
    neither on a Pi, and falls back to software without complaint; the Pi's
    H.264 block is reached through V4L2 M2M and is never tried. Measured on
    the Pi 4 bench, same 720p file: load 0.62 with `v4l2m2m-copy` against 1.65
    without. The Zero 2 W has a quarter of that CPU, so this is the difference
    between SPEC decision 16 holding and not.

    And **video is only requested when a display is actually connected**. With
    `vo=drm` and nothing plugged in, mpv fails to open the output and then
    loads no file at all — not even the audio track. The device would sit
    silent whenever it was used without a projector, which SPEC's "when no
    HDMI is connected, playback is audio-only" explicitly allows for.

    An absent display therefore turns video *off* (`vid=no`) rather than
    simply leaving the options empty. Empty looks equivalent and is not: it
    hands mpv its own default output chain, which on a headless Pi hunts for
    an X11, Wayland or DRM target that does not exist. mpv keeps serving
    properties for a while and then stops answering one — and because the
    app reads `volume` from the loop thread every tick, the whole appliance
    wedges there with the keypad, the keyboard and the panel all frozen
    together. It looks exactly like dead controls, and it is not.

    This is the common case, not the edge case: the device is used without a
    projector most of the time.

    Returns nothing on a dev machine either: macOS has no DRM, and a Linux
    desktop with a display server keeps mpv's own windowed defaults.

    The original Zero W (armv6l) gets a different output chain, and the
    ALABANZA_VIDEO environment variable can replace the whole set for bench
    measurements -- see the code below.
    """
    if sys.platform != "linux":
        return {}
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return {}
    device = _drm_device()
    if device is None:
        return {"vid": "no"}
    override = _video_override()
    if override is not None:
        override.setdefault("drm_device", device)
        return override
    if _machine() == "armv6l":
        # The original Pi Zero W: one ARM11 core, no NEON, about an eighth of
        # a Zero 2 W. `vo=drm` converts every decoded frame from YUV to RGB in
        # software, which that core cannot do at 720p25. `vo=gpu` on the DRM
        # context uploads the YUV planes as textures and lets the VideoCore
        # do the conversion; the copy out of the decoder is a plain memcpy
        # the ARM11 can afford. Untested at the time of writing -- the
        # ALABANZA_VIDEO override above exists so this can be measured on
        # the board without editing code.
        return {"vo": "gpu", "gpu_context": "drm", "drm_device": device,
                "hwdec": "v4l2m2m-copy"}
    return {"vo": "drm", "drm_device": device, "hwdec": "v4l2m2m-copy"}


def _machine() -> str:
    return platform.machine()


def _video_override() -> dict | None:
    """Bench override: ALABANZA_VIDEO="vo=gpu,gpu-context=drm,hwdec=drm-prime".

    Comma-separated mpv options, exactly as they would be written on the mpv
    command line minus the leading dashes. Only read when a display is
    connected, so it can never turn video on where the probe turned it off.
    Meant for measuring decode paths on a board, never for production.
    """
    raw = os.environ.get("ALABANZA_VIDEO", "").strip()
    if not raw:
        return None
    options = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        key, _, value = item.partition("=")
        options[key.strip().replace("-", "_")] = value.strip() or "yes"
    return options


class Player:
    def __init__(self, video: bool = True, idle_images: list[Path] | None = None):
        self._idle_images = _idle_images() if idle_images is None else idle_images
        self._idle_shown: Path | None = None
        self._idle_queue: list[Path] = []
        self._showing_idle = False
        self._starting_until = 0.0
        options = {
            "vid": "auto" if video else "no",
            "osc": False,
            "force_window": False,
            # Hold the last frame at the end instead of unloading. Unloading
            # releases DRM, so the Linux console appeared on the projector for
            # the tick between a hymn ending and the idle image loading. With
            # keep-open the final frame stays up and the image loads over it,
            # and the end is detected by eof-reached instead of by the file
            # disappearing. SPEC decision 8: the projector shows the video,
            # the image, or a freeze-frame, and never anything else.
            "keep_open": True,
            "log_handler": None,
            # mpv ships a Lua script each for the OSC, stats, console,
            # ytdl, select, positioning and commands, and starts a Lua VM
            # per script. None can do anything on a device with no window
            # and no keyboard, and on the Zero W they are measurable startup
            # time and seven idle threads. (--load-scripts=no would not do:
            # it only covers user scripts, not these built-ins.)
            "ytdl": False,
            "load_stats_overlay": False,
            "load_console": False,
            "load_select": False,
            "load_positioning": False,
            "load_commands": False,
        }
        # One dict rather than keywords plus a splat, because the probe has to
        # be able to override `vid` — with no display attached it turns video
        # off — and mpv.MPV(vid=..., **{"vid": ...}) is a TypeError.
        options.update(_video_options() if video else {})
        self._mpv = mpv.MPV(**options)
        # Whether video is *actually* on, which is not the same as what the
        # caller asked for: --no-video and an unplugged HDMI arrive at the
        # same place, and everything downstream has to treat them alike.
        self._video = options["vid"] != "no"
        self._mpv.volume = 80
        if self._video:
            # Without this an image would be shown for one second and then
            # unloaded, leaving a black screen.
            self._mpv["image-display-duration"] = "inf"
            self.show_idle()

    # -- lifecycle -----------------------------------------------------
    def play(self, path: Path) -> None:
        self._showing_idle = False
        self._starting_until = time.monotonic() + START_GRACE
        self._mpv.speed = 1.0  # spec: speed resets per hymn
        self._mpv.play(str(path))
        self._mpv.pause = False

    def show_idle(self) -> None:
        """Put a static image back on HDMI, chosen at random.

        The image goes through the same mpv instance the hymns use, so
        swapping between them is one load and the screen never blanks in
        between. It is loaded like any other file, which is why `active` has
        to exclude it: the whole state machine reads `active` as "a hymn is
        loaded", and an idle picture must not look like one.

        Shuffled deck rather than an independent draw each time. Picking at
        random repeats: it produced 04, 05, 04, 05 on the bench, and a verse
        alternating with one other looks like a fault, not like chance. A deck
        also means a congregation sees every verse over a service instead of
        the same two all morning. Reshuffled when exhausted, never starting on
        the one still on screen.
        """
        if not self._video:
            return                      # audio-only: there is nothing to show
        pool = [p for p in self._idle_images if p.exists()]
        if not pool:
            return
        if not self._idle_queue:
            self._idle_queue = random.sample(pool, len(pool))
            if len(self._idle_queue) > 1 and self._idle_queue[0] == self._idle_shown:
                self._idle_queue.append(self._idle_queue.pop(0))
        chosen = self._idle_queue.pop(0)
        self._starting_until = 0.0
        self._mpv.play(str(chosen))
        self._mpv.pause = False
        self._idle_shown = chosen
        self._showing_idle = True

    def toggle_pause(self) -> None:
        if self.active:
            self._mpv.pause = not self._mpv.pause

    def stop(self) -> None:
        # Load the image straight over the hymn rather than stopping first.
        # mpv.stop() would unload, and an unloaded mpv shows the console.
        self._starting_until = 0.0
        if self._video and self._idle_images:
            self.show_idle()
        else:
            self._mpv.stop()

    def shutdown(self) -> None:
        self._mpv.terminate()

    # -- state ---------------------------------------------------------
    @property
    def active(self) -> bool:
        """A *hymn* is loaded, starting, playing or paused.

        Two things this must get right, both learned the hard way.

        The idle image is loaded in mpv too and deliberately does not count:
        every caller means "is a hymn on" — whether Play pauses, whether Stop
        has anything to stop, whether a lost speaker should pause playback.

        And a hymn that is still *loading* counts. mpv is asynchronous:
        play() returns in about a millisecond, `filename` appears about twelve
        later. app.tick() runs microseconds after app.handle(), so it lands
        inside that window and used to read a starting hymn as a finished one
        — clearing now_playing and putting the idle image back over a hymn
        that had only just begun. The operator saw a keypress do nothing and
        pressed again.
        """
        if self._showing_idle:
            return False
        if self._mpv.filename is not None:
            self._starting_until = 0.0
            # keep-open holds the last frame rather than unloading, so a
            # finished hymn still has a filename. eof-reached is what says
            # it is over.
            return not self._mpv.eof_reached
        return time.monotonic() < self._starting_until

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
        new = min(100, max(0, self.volume + direction))    # 1% per click
        self._mpv.volume = new
        return new
