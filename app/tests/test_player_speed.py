"""Which stretcher a speed change uses, and when it is in the chain.

mpv preserves pitch across a speed change with scaletempo2, which the Zero W
cannot afford on top of a Bluetooth stream: every speed change in the first
church test broke the audio up. That board uses the older scaletempo, and
only while the speed is off 100%, because parked in the chain it still costs
nine points of the core. See player._speed_filter.
"""

import pytest

pytest.importorskip("mpv")           # needs libmpv; brew install mpv

from alabanza import player                                       # noqa: E402


class TestWhichFilter:
    def test_the_zero_w_stretches_with_the_cheap_filter(self):
        assert player._speed_filter(1.05, "armv6l") == "scaletempo=search=10"
        assert player._speed_filter(0.75, "armv6l") == "scaletempo=search=10"

    def test_but_not_at_full_speed(self):
        assert player._speed_filter(1.0, "armv6l") == ""

    def test_the_other_boards_keep_mpvs_own(self):
        assert player._speed_filter(1.25, "aarch64") == ""
        assert player._speed_filter(1.0, "aarch64") == ""


class FakeMPV:
    """Records every property assignment, in order."""

    def __init__(self, **options):
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "speed", 1.0)
        object.__setattr__(self, "af", "")

    def __setattr__(self, name, value):
        self.log.append((name, value))
        object.__setattr__(self, name, value)

    def __getitem__(self, key):
        return None

    def __setitem__(self, key, value):
        pass

    def play(self, path):
        self.log.append(("play", path))

    def terminate(self):
        pass


@pytest.fixture
def zero_w(monkeypatch):
    monkeypatch.setattr(player, "_machine", lambda: "armv6l")
    monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
    p = player.Player(video=False, idle_images=[])
    p._mpv.log.clear()
    return p


@pytest.fixture
def pi4(monkeypatch):
    monkeypatch.setattr(player, "_machine", lambda: "aarch64")
    monkeypatch.setattr(player.mpv, "MPV", FakeMPV)
    p = player.Player(video=False, idle_images=[])
    p._mpv.log.clear()
    return p


class TestTheChainFollowsTheSpeed:
    def test_the_filter_goes_in_before_the_speed_leaves_100(self, zero_w):
        assert zero_w.nudge_speed(+1) == 1.05
        assert zero_w._mpv.log == [("af", "scaletempo=search=10"), ("speed", 1.05)]

    def test_further_steps_leave_the_chain_alone(self, zero_w):
        zero_w.nudge_speed(+1)
        zero_w._mpv.log.clear()
        zero_w.nudge_speed(+1)
        assert zero_w._mpv.log == [("speed", 1.1)]

    def test_the_filter_comes_out_after_the_speed_is_back_at_100(self, zero_w):
        zero_w.nudge_speed(+1)
        zero_w._mpv.log.clear()
        zero_w.nudge_speed(-1)
        assert zero_w._mpv.log == [("speed", 1.0), ("af", "")]

    def test_a_new_hymn_resets_both(self, zero_w, tmp_path):
        zero_w.nudge_speed(-1)
        zero_w._mpv.log.clear()
        zero_w.play(tmp_path / "001.mp4")
        assert zero_w._mpv.log[:2] == [("speed", 1.0), ("af", "")]
        assert zero_w._mpv.speed == 1.0

    def test_a_new_hymn_at_full_speed_does_not_touch_the_chain(self, zero_w, tmp_path):
        zero_w.play(tmp_path / "001.mp4")
        assert ("af", "") not in zero_w._mpv.log

    def test_the_other_boards_never_touch_the_chain(self, pi4):
        pi4.nudge_speed(+1)
        pi4.nudge_speed(-1)
        assert [n for n, _ in pi4._mpv.log] == ["speed", "speed"]
