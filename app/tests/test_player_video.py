"""Which video options mpv gets, and why an empty dict is not "no video".

The appliance spends most of its life with nothing plugged into HDMI. That
path used to hand mpv its own default output chain, which on a headless Pi
hunts for an X11/Wayland/DRM target that cannot exist; mpv then stopped
answering a property read and the whole loop wedged inside `volume` — the
keypad, the keyboard and the panel all frozen at once. So the no-display
case has to turn video *off* explicitly, and that is what these check.
"""

import pytest

pytest.importorskip("mpv")           # needs libmpv; brew install mpv

from alabanza import player                                       # noqa: E402


@pytest.fixture
def headless(monkeypatch):
    """A Pi with no display server — the device, over SSH.

    The machine is pinned to the production board, so these pass the same
    on a laptop, the Pi 4 and the Zero W; the armv6l tests below override
    it, because run on a real Zero W the probe would otherwise answer for
    the box it is on rather than the one under test."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("ALABANZA_VIDEO", raising=False)
    monkeypatch.setattr(player, "_machine", lambda: "aarch64")


class TestNoDisplayMeansNoVideo:
    def test_an_unplugged_hdmi_turns_video_off(self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: None)
        assert player._video_options() == {"vid": "no"}

    def test_it_is_never_merely_empty(self, headless, monkeypatch):
        """An empty dict is the bug: it means "mpv, you decide", and what it
        decides on a headless Pi is an output that does not exist."""
        monkeypatch.setattr(player, "_drm_device", lambda: None)
        assert player._video_options() != {}

    def test_a_connected_display_still_gets_drm_and_hardware_decode(
            self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: "/dev/dri/card1")
        options = player._video_options()
        assert options["vo"] == "drm"
        assert options["drm_device"] == "/dev/dri/card1"
        assert options["hwdec"] == "v4l2m2m-copy", \
            "software decode is 3x the load on a Zero 2 W"
        assert "vid" not in options


class TestTheOriginalZeroW:
    """armv6l has one ARM11 core with no NEON. Software YUV-to-RGB at 720p is
    beyond it, so the frame goes to the GPU as textures instead."""

    def test_armv6_renders_through_the_gpu_on_drm(self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: "/dev/dri/card0")
        monkeypatch.setattr(player, "_machine", lambda: "armv6l")
        options = player._video_options()
        assert options["vo"] == "gpu"
        assert options["gpu_context"] == "drm"
        assert options["drm_device"] == "/dev/dri/card0"
        assert options["hwdec"] == "v4l2m2m-copy"

    def test_armv6_without_a_display_is_still_audio_only(
            self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: None)
        monkeypatch.setattr(player, "_machine", lambda: "armv6l")
        assert player._video_options() == {"vid": "no"}

    def test_the_other_boards_keep_the_drm_path(self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: "/dev/dri/card1")
        monkeypatch.setattr(player, "_machine", lambda: "aarch64")
        assert player._video_options()["vo"] == "drm"


class TestTheBenchOverride:
    def test_alabanza_video_replaces_the_chain(self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: "/dev/dri/card1")
        monkeypatch.setenv("ALABANZA_VIDEO", "vo=gpu, gpu-context=drm,hwdec=drm-prime")
        assert player._video_options() == {
            "vo": "gpu", "gpu_context": "drm", "hwdec": "drm-prime",
            "drm_device": "/dev/dri/card1"}

    def test_it_cannot_turn_video_on_without_a_display(
            self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: None)
        monkeypatch.setenv("ALABANZA_VIDEO", "vo=gpu")
        assert player._video_options() == {"vid": "no"}

    def test_a_bare_flag_means_yes(self, headless, monkeypatch):
        monkeypatch.setattr(player, "_drm_device", lambda: "/dev/dri/card1")
        monkeypatch.setenv("ALABANZA_VIDEO", "vo=drm,hwdec")
        assert player._video_options()["hwdec"] == "yes"


class TestTheDevMachineIsUntouched:
    def test_a_display_server_keeps_mpvs_own_defaults(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert player._video_options() == {}

    def test_macos_keeps_mpvs_own_defaults(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "darwin")
        assert player._video_options() == {}


class TestTheOptionsCanBeMerged:
    def test_vid_is_overridable_without_a_duplicate_keyword(
            self, headless, monkeypatch):
        """Player builds one dict precisely so the probe can override `vid`.
        Passing it as a keyword *and* splatting the probe in is a TypeError,
        which is how the first attempt at this fix broke."""
        monkeypatch.setattr(player, "_drm_device", lambda: None)
        options = {"vid": "auto", "osc": False}
        options.update(player._video_options())
        assert options["vid"] == "no"
        assert len([k for k in options if k == "vid"]) == 1
