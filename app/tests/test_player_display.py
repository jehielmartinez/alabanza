"""Picking up a projector switched on after the box booted.

The DRM probe runs once, in the constructor, and on this device the box is
routinely switched on first — and the projector sleeps between services.
"Nothing plugged in" at that instant used to mean no video for the whole
morning: no screensaver, no verses, hymns audio-only, and nothing on the
panel to say why. Only restarting the unit recovered it.
"""

import time

import pytest

pytest.importorskip("mpv")           # needs libmpv; brew install mpv

from alabanza import player                                       # noqa: E402

from test_player_repaint import FakeMPV, settle                   # noqa: E402

CONNECTED = {"vo": "drm", "drm_device": "/dev/dri/card0", "hwdec": "v4l2m2m-copy"}
BLIND = {"vid": "no"}


@pytest.fixture
def blind(monkeypatch):
    """A player that booted with nothing plugged into HDMI."""
    monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
    monkeypatch.setattr(player, "_video_options", lambda: dict(BLIND))
    p = player.Player(video=True, idle_images=[])
    assert p._video is False
    p._mpv.log.clear()
    yield p
    p.shutdown()


def plug_in(monkeypatch):
    monkeypatch.setattr(player, "_video_options", lambda: dict(CONNECTED))


class TestItLooksAgain:
    def test_a_blind_player_opens_when_a_display_turns_up(self, blind, monkeypatch):
        assert blind.poll_display(now=100.0) is False, "nothing plugged in yet"
        plug_in(monkeypatch)
        assert blind.poll_display(now=200.0) is True
        assert blind._video is True

    def test_it_says_so_only_once(self, blind, monkeypatch):
        plug_in(monkeypatch)
        assert blind.poll_display(now=200.0) is True
        assert blind.poll_display(now=300.0) is False, \
            "the panel would announce the projector every two seconds"

    def test_it_does_not_read_sysfs_every_tick(self, blind, monkeypatch):
        reads = []
        monkeypatch.setattr(player, "_video_options",
                            lambda: reads.append(1) or dict(BLIND))
        for tick in range(40):                  # two seconds of a 50 ms loop
            blind.poll_display(now=100.0 + tick * 0.05)
        assert len(reads) == 1, "one probe per DISPLAY_POLL_S, not one per tick"

    def test_and_stops_looking_once_there_is_one(self, blind, monkeypatch):
        plug_in(monkeypatch)
        blind.poll_display(now=200.0)
        reads = []
        monkeypatch.setattr(player, "_video_options",
                            lambda: reads.append(1) or dict(CONNECTED))
        for tick in range(100):
            blind.poll_display(now=300.0 + tick)
        assert reads == [], "there is nothing left to look for"

    def test_the_poll_is_free_on_a_player_that_had_a_display_all_along(self, monkeypatch):
        monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
        monkeypatch.setattr(player, "_video_options", lambda: dict(CONNECTED))
        p = player.Player(video=True, idle_images=[])
        try:
            assert p._video is True
            assert p.poll_display(now=100.0) is False
        finally:
            p.shutdown()

    def test_video_off_by_request_is_not_a_missing_display(self, monkeypatch):
        """--no-video is a choice, not a projector that has not arrived; it
        must not be undone by one being plugged in."""
        monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
        plug_in(monkeypatch)
        p = player.Player(video=False, idle_images=[])
        try:
            assert p.poll_display(now=200.0) is False
            assert p._video is False
        finally:
            p.shutdown()


class TestWhatOpeningDoes:
    def test_mpv_gets_the_whole_chain_with_vid_last(self, blind, monkeypatch):
        plug_in(monkeypatch)
        blind.poll_display(now=200.0)
        written = [k for k, _ in blind._mpv.log]
        for key in ("vo", "drm-device", "hwdec", "vid"):
            assert key in written, f"{key} never reached mpv"
        assert written.index("vid") > written.index("vo"), \
            "selecting the track before the output is where it hunts for one"

    def test_the_screensaver_goes_up(self, blind, monkeypatch, tmp_path):
        image = tmp_path / "screensaver-01.png"
        image.write_bytes(b"")
        blind._idle_images = [image]
        plug_in(monkeypatch)
        blind.poll_display(now=200.0)
        assert ("play", str(image)) in blind._mpv.log

    def test_a_hymn_already_playing_is_not_interrupted(self, blind, monkeypatch,
                                                       tmp_path):
        blind.play(tmp_path / "001.mp4")
        blind._mpv.log.clear()
        plug_in(monkeypatch)
        blind.poll_display(now=200.0)
        assert not any(k == "play" for k, _ in blind._mpv.log), \
            "the hymn gains its picture; it does not start again"

    def test_stills_get_a_repainter_they_did_not_have(self, blind, monkeypatch,
                                                      tmp_path):
        assert blind._repaint is None, "nothing to repaint while blind"
        image = tmp_path / "screensaver-01.png"
        image.write_bytes(b"")
        blind._idle_images = [image]        # or there is no still to push out
        plug_in(monkeypatch)
        blind.poll_display(now=200.0)
        assert blind._repaint is not None
        assert settle(lambda: blind._repaint.nudges > 0), \
            "the screensaver it just put up needs pushing out like any still"


class TestWhenOpeningFails:
    def test_it_stays_blind_and_keeps_the_reason(self, blind, monkeypatch):
        plug_in(monkeypatch)
        monkeypatch.setattr(blind._mpv, "raises", RuntimeError("card busy"))
        assert blind.poll_display(now=200.0) is False
        assert blind._video is False
        assert isinstance(blind.last_display_error, RuntimeError)

    def test_and_tries_again_on_the_next_poll(self, blind, monkeypatch):
        plug_in(monkeypatch)
        monkeypatch.setattr(blind._mpv, "raises", RuntimeError("card busy"))
        assert blind.poll_display(now=200.0) is False
        monkeypatch.setattr(blind._mpv, "raises", None)
        assert blind.poll_display(now=300.0) is True, \
            "a display that half-appears is likelier than one gone for good"


class TestOnThePanel:
    def test_the_operator_is_told(self, harness):
        rig = harness()
        rig.player.display_appears = True
        assert "Proyector" in rig.app.tick().hint

    def test_and_not_told_again_once_it_has_faded(self, harness):
        rig = harness()
        rig.player.display_appears = True
        rig.app.tick()
        assert "Proyector" not in rig.advance(5.0).hint
        assert "Proyector" not in rig.advance(30.0).hint, \
            "a projector announced every two seconds for the whole service"

    def test_nothing_is_said_when_nothing_changed(self, harness):
        rig = harness()
        assert "Proyector" not in rig.app.tick().hint

    def test_it_does_not_interrupt_what_the_operator_was_doing(self, harness):
        """It is a flash like every other message: the mode stands and a
        number half-typed when the projector warms up is still there."""
        rig = harness()
        rig.type_number(279)
        mode = rig.app.mode
        rig.player.display_appears = True
        vm = rig.app.tick()
        assert "Proyector" in vm.hint
        assert rig.app.mode is mode
        assert rig.app.entry == "279"

    def test_the_flash_clears(self, harness):
        rig = harness()
        rig.player.display_appears = True
        rig.app.tick()
        vm = rig.advance(5.0)
        assert "Proyector" not in vm.hint


def test_the_poll_interval_is_measured_in_seconds_not_ticks():
    # 50 ms loop; anything under a second would be a sysfs read every few
    # ticks for the whole service on the boards that never see a projector.
    assert 1.0 <= player.DISPLAY_POLL_S <= 10.0


def test_a_real_poll_uses_the_wall_clock_when_it_is_given_none(monkeypatch):
    """__main__ has no clock to hand; App passes its own."""
    monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
    monkeypatch.setattr(player, "_video_options", lambda: dict(BLIND))
    p = player.Player(video=True, idle_images=[])
    try:
        assert p.poll_display() is False
        assert p._next_display_poll > time.monotonic()
    finally:
        p.shutdown()
