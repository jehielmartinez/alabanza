"""Pushing a still out of the back buffer — player._StillRepaint.

The Zero W will not scan out a still whose size matches the one already on
screen: it is decoded, rendered, reported shown, and the projector keeps the
previous picture. Only a load that changes the video size lands. Writing a
video property redraws the frame, and that redraw is the present the still
never got. These check that the nudge happens, stops when it should, and
never costs the loop thread anything.
"""

import threading
import time

import pytest

pytest.importorskip("mpv")           # needs libmpv; brew install mpv

from alabanza import player                                       # noqa: E402

FAST = (0.0, 0.01, 0.02)             # the schedule, minus the waiting


class FakeMPV:
    """Records property assignments both ways round, thread-safely: the
    nudges arrive on the repaint thread and the assertions read from the
    test's."""

    def __init__(self, **options):
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "_guard", threading.Lock())
        object.__setattr__(self, "raises", None)
        object.__setattr__(self, "speed", 1.0)
        object.__setattr__(self, "af", "")
        object.__setattr__(self, "pause", False)
        object.__setattr__(self, "volume", 0)
        object.__setattr__(self, "filename", None)      # what Player.active reads
        object.__setattr__(self, "eof_reached", False)

    def __setattr__(self, name, value):
        with self._guard:
            self.log.append((name, value))
        object.__setattr__(self, name, value)

    def __getitem__(self, key):
        return None

    def __setitem__(self, key, value):
        if self.raises is not None:
            raise self.raises
        with self._guard:
            self.log.append((key, value))

    def writes(self, key):
        with self._guard:
            return [v for k, v in self.log if k == key]

    def play(self, path):
        with self._guard:
            self.log.append(("play", path))

    def terminate(self):
        pass


def settle(predicate, timeout=2.0):
    """Wait for a background thread to get there, without sleeping the whole
    timeout when it already has."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def handle():
    return FakeMPV()


@pytest.fixture
def repaint(handle):
    worker = player._StillRepaint(handle, schedule=FAST)
    yield worker
    worker.close()


class TestTheNudge:
    def test_a_kick_redraws_the_frame(self, repaint, handle):
        repaint.kick()
        assert settle(lambda: repaint.nudges >= len(FAST)), \
            "the whole schedule should run: the load it chases is asynchronous"
        assert handle.writes("video-zoom"), "nothing was written to redraw with"

    def test_it_leaves_the_picture_where_it_found_it(self, repaint, handle):
        repaint.kick()
        settle(lambda: repaint.nudges >= len(FAST))
        assert handle.writes("video-zoom")[-1] == 0.0, \
            "a zoom left in place would be a permanently scaled projector"

    def test_the_zoom_is_too_small_to_see(self):
        # 0.01% of 1280 px is an eighth of a pixel, and it is put back in the
        # same breath; anything bigger would be a visible twitch per slide.
        assert 0 < player.REPAINT_ZOOM <= 0.001

    def test_nothing_happens_without_a_kick(self, repaint, handle):
        time.sleep(0.05)
        assert repaint.nudges == 0
        assert handle.writes("video-zoom") == []


class TestWhenItStops:
    def test_a_hymn_cancels_the_pending_nudges(self, handle):
        worker = player._StillRepaint(handle, schedule=(0.0, 5.0))
        try:
            worker.kick()
            settle(lambda: worker.nudges >= 1)
            worker.cancel()
            done = worker.nudges
            time.sleep(0.05)
            assert worker.nudges == done, \
                "nudging through a hymn rebuilds the render chain under it"
        finally:
            worker.close()

    def test_a_newer_still_supersedes_the_one_being_chased(self, handle):
        worker = player._StillRepaint(handle, schedule=(0.0, 5.0))
        try:
            worker.kick()
            settle(lambda: worker.nudges >= 1)
            worker.kick()
            assert settle(lambda: worker.nudges >= 2), \
                "the second still needs its own schedule, from its own load"
        finally:
            worker.close()

    def test_close_returns_even_mid_schedule(self, handle):
        worker = player._StillRepaint(handle, schedule=(0.0, 30.0))
        worker.kick()
        settle(lambda: worker.nudges >= 1)
        started = time.monotonic()
        worker.close()
        assert time.monotonic() - started < 1.0, "shutdown must not wait out a schedule"


class TestItNeverTakesTheAppDown:
    def test_a_failing_nudge_is_kept_but_not_raised(self, handle):
        handle.raises = RuntimeError("no display")
        worker = player._StillRepaint(handle, schedule=FAST)
        try:
            worker.kick()
            assert settle(lambda: worker.last_error is not None)
            assert isinstance(worker.last_error, RuntimeError)
            assert worker.nudges == 0
        finally:
            worker.close()

    def test_and_it_keeps_trying_afterwards(self, handle):
        handle.raises = RuntimeError("transient")
        worker = player._StillRepaint(handle, schedule=(0.0, 0.01, 0.02, 0.03))
        try:
            worker.kick()
            settle(lambda: worker.last_error is not None)
            handle.raises = None
            worker.kick()
            assert settle(lambda: worker.nudges >= 1), \
                "an I2C-style glitch is transient; a dead repainter is not"
        finally:
            worker.close()

    def test_the_kick_does_not_block_the_caller(self, repaint):
        # Slides._render calls show_image with its lock held, and the loop
        # thread takes that lock on the next turn of the wheel.
        started = time.monotonic()
        for _ in range(50):
            repaint.kick()
        assert time.monotonic() - started < 0.05


class TestThePlayerWiresItUp:
    @pytest.fixture
    def with_video(self, monkeypatch):
        monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
        monkeypatch.setattr(player, "_video_options", lambda: {})
        p = player.Player(video=True, idle_images=[])
        yield p
        p.shutdown()

    def test_a_still_kicks_the_repainter(self, with_video, tmp_path):
        before = with_video._repaint.nudges
        with_video.show_image(tmp_path / "verse-0.bmp")
        assert settle(lambda: with_video._repaint.nudges > before)

    def test_a_hymn_does_not(self, with_video, tmp_path):
        with_video.show_image(tmp_path / "verse-0.bmp")
        settle(lambda: with_video._repaint.nudges > 0)
        with_video.play(tmp_path / "001.mp4")
        settled = with_video._repaint.nudges
        time.sleep(0.05)
        assert with_video._repaint.nudges == settled

    def test_no_display_means_no_repaint_thread(self, monkeypatch, tmp_path):
        monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
        monkeypatch.setattr(player, "_video_options", lambda: {"vid": "no"})
        p = player.Player(video=True, idle_images=[])
        assert p._repaint is None, "nothing to repaint with nothing plugged in"
        p.show_image(tmp_path / "verse-0.bmp")        # must not explode
        p.shutdown()

    def test_shutdown_stops_the_thread(self, monkeypatch):
        monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
        monkeypatch.setattr(player, "_video_options", lambda: {})
        p = player.Player(video=True, idle_images=[])
        worker = p._repaint
        p.shutdown()
        assert not worker._thread.is_alive()
