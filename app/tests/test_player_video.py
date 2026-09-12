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
    """A Pi with no display server — the device, over SSH."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


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
