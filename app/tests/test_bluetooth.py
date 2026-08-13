"""Bluetooth: the failure paths, mostly.

Bluetooth breaks during a service, not on a bench, so what is pinned here is
what happens when a speaker refuses to pair, never answers, or dies mid-hymn.
The fake backend ages on the same injected clock as the app, so a 30 s timeout
is instant and exact. Design: docs/BLUETOOTH.md.
"""

import pytest

from alabanza.app import Mode
from alabanza.bluetooth import ERR_OFF, ERR_PAIR, ERR_TIMEOUT, NullBackend, visible
from alabanza.bt_fake import FakeBackend
from alabanza.events import Kind
from alabanza.settings import Settings

JBL = "AA:BB:CC:00:00:01"        # pairs and connects normally; starts paired
IGLESIA = "AA:BB:CC:00:00:02"    # connects, then drops 20 s later
SOUNDCORE = "AA:BB:CC:00:00:03"  # pairing always fails
VIEJA = "AA:BB:CC:00:00:04"      # never answers a connect
PHONE = "AA:BB:CC:00:00:05"      # not an audio device


@pytest.fixture
def bt_rig(harness, clock):
    def build(*, paired=(JBL,), output="jack", last="", available=True):
        backend = FakeBackend(paired=paired, clock=clock, available=available)
        settings = Settings(output=output, last_bt_device=last)
        rig = harness(bt=backend, settings=settings)
        return rig
    return build


def open_bluetooth(rig):
    """Menu -> Bluetooth, the way an operator gets there."""
    rig.press(Kind.PUSH)
    while "Bluetooth" not in (rig.cursor_row() or ""):
        rig.press(Kind.DOWN)
    return rig.press(Kind.CONFIRM)


def select(rig, name):
    """Turn the encoder until `name` is under the cursor."""
    for _ in range(12):
        if name in (rig.cursor_row() or ""):
            return rig.tick()
        rig.press(Kind.DOWN)
    raise AssertionError(f"{name} never appeared: {rig.rows()}")


class TestFindingAndPairing:
    def test_opening_the_screen_starts_looking_by_itself(self, bt_rig):
        rig = bt_rig()
        open_bluetooth(rig)
        assert rig.app.mode is Mode.BT_LIST
        assert rig.bt.state().scanning, "scanning must not need its own key"

    def test_phones_and_laptops_never_appear(self, bt_rig):
        rig = bt_rig()
        open_bluetooth(rig)
        rig.advance(6)
        macs = [d.mac for d in visible(rig.bt.state().devices)]
        assert PHONE not in macs
        assert JBL in macs

    def test_pairing_an_unpaired_speaker_also_connects_it(self, bt_rig):
        rig = bt_rig(paired=())
        open_bluetooth(rig)
        rig.advance(6)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM)
        assert rig.bt.state().busy_op == "pair"
        rig.advance(8)
        assert rig.bt.state().connected_mac == JBL

    def test_connecting_remembers_the_speaker_for_next_boot(self, bt_rig):
        rig = bt_rig(paired=())
        open_bluetooth(rig)
        rig.advance(6)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM)
        rig.advance(8)
        assert rig.app.settings.last_bt_device == JBL
        assert rig.app.settings.bt_names[JBL] == "JBL Flip 5"

    def test_scanning_stops_once_something_is_connected(self, bt_rig):
        rig = bt_rig(paired=())
        open_bluetooth(rig)
        rig.advance(6)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM)
        rig.advance(8)
        assert not rig.bt.state().scanning

    def test_discovery_gives_up_after_30_seconds(self, bt_rig):
        rig = bt_rig()
        open_bluetooth(rig)
        rig.advance(20)
        assert rig.bt.state().scanning
        rig.advance(15)
        assert not rig.bt.state().scanning


class TestFailures:
    def test_a_speaker_that_refuses_to_pair_says_why(self, bt_rig):
        rig = bt_rig(paired=())
        open_bluetooth(rig)
        rig.advance(6)
        select(rig, "Soundcore")
        rig.press(Kind.CONFIRM)
        rig.advance(8)
        assert rig.message == ERR_PAIR
        assert rig.bt.state().connected_mac == ""

    def test_a_speaker_that_never_answers_is_timed_out_by_the_app(self, bt_rig):
        rig = bt_rig(paired=(VIEJA,))
        open_bluetooth(rig)
        select(rig, "Bocina Vieja")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)          # open device -> Conectar
        assert rig.bt.state().busy_op == "connect"
        rig.advance_until(lambda r: r.message == ERR_TIMEOUT)
        assert rig.bt.state().busy_op == "", "the op must be abandoned, not left hanging"

    def test_an_operator_can_cancel_a_slow_operation(self, bt_rig):
        rig = bt_rig(paired=(VIEJA,))
        open_bluetooth(rig)
        select(rig, "Bocina Vieja")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)
        rig.advance(2)
        rig.press(Kind.STAR)
        assert rig.bt.state().busy_op == ""
        assert rig.message == "Cancelado"

    def test_a_cancel_does_not_swallow_the_next_command(self, bt_rig):
        """The cached snapshot is a tick old; a stale busy_op used to eat it."""
        rig = bt_rig(paired=(VIEJA, JBL))
        open_bluetooth(rig)
        select(rig, "Bocina Vieja")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)
        rig.press(Kind.STAR)                           # cancel; back on the list
        select(rig, "JBL")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)
        assert rig.bt.state().busy_op == "connect"

    def test_no_adapter_is_reported_not_crashed_into(self, harness):
        rig = harness(bt=NullBackend())
        open_bluetooth(rig)
        assert ERR_OFF in "".join(rig.rows())


class TestTheSpeakerDiesMidHymn:
    def playing_on_bluetooth(self, bt_rig):
        rig = bt_rig(paired=(IGLESIA,), output="bluetooth", last=IGLESIA)
        rig.advance(5)                                 # boot auto-reconnect
        assert rig.bt.state().connected_mac == IGLESIA
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        assert rig.player.active and not rig.player.paused
        return rig

    def test_boot_reconnects_to_the_last_speaker(self, bt_rig):
        rig = bt_rig(paired=(IGLESIA,), output="bluetooth", last=IGLESIA)
        rig.advance(5)
        assert rig.bt.state().connected_mac == IGLESIA

    def test_boot_leaves_the_adapter_alone_when_bt_is_not_the_output(self, bt_rig):
        rig = bt_rig(paired=(IGLESIA,), output="jack", last=IGLESIA)
        rig.advance(5)
        assert rig.bt.state().connected_mac == "", "decision 9: only chase when BT is selected"

    def test_it_pauses_rather_than_playing_into_nothing(self, bt_rig):
        rig = self.playing_on_bluetooth(bt_rig)
        rig.advance_until(lambda r: r.player.paused)   # it drops at +20 s
        assert rig.player.active, "paused, not stopped — the hymn keeps its place"
        assert "BT perdido" in rig.message

    def test_the_status_bar_shows_the_output_is_gone(self, bt_rig):
        rig = self.playing_on_bluetooth(bt_rig)
        vm = rig.advance_until(lambda r: r.player.paused)
        assert vm.output_state in ("down", "connecting")

    def test_it_recovers_by_itself_but_never_resumes(self, bt_rig):
        rig = self.playing_on_bluetooth(bt_rig)
        rig.advance_until(lambda r: r.player.paused)
        rig.advance_until(lambda r: r.bt.state().connected_mac == IGLESIA)
        assert rig.player.paused, "a hymn restarting on its own is worse than silence"
        assert rig.message == "Reconectado - Play"

    def test_a_disconnect_we_asked_for_raises_no_alarm(self, bt_rig):
        rig = bt_rig(paired=(JBL,))
        open_bluetooth(rig)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)          # Conectar
        rig.advance_until(lambda r: r.bt.state().connected_mac == JBL)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)          # Desconectar
        rig.advance_until(lambda r: r.bt.state().connected_mac == "")
        assert rig.message == "Desconectado"


class TestPlayingWithNoSpeaker:
    def test_play_is_refused_and_says_so(self, bt_rig):
        rig = bt_rig(paired=(VIEJA,), output="bluetooth", last=VIEJA)
        rig.advance_until(lambda r: r.message == "BT: no conectado")
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        assert not rig.player.played
        assert rig.message == "BT: no conectado"

    def test_the_refusal_also_fires_one_quiet_retry(self, bt_rig):
        """So the operator's instinctive second press is the one that works."""
        rig = bt_rig(paired=(VIEJA,), output="bluetooth", last=VIEJA)
        rig.advance_until(lambda r: r.message == "BT: no conectado")
        assert rig.bt.state().busy_op == ""
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        assert rig.bt.state().busy_op == "connect", "play should retry in the background"

    def test_giving_up_is_said_once_not_three_times(self, bt_rig):
        """Three attempts, three timeouts, but only the last one speaks."""
        rig = bt_rig(paired=(VIEJA,), output="bluetooth", last=VIEJA)
        seen = []
        for _ in range(1400):
            rig.clock.advance(0.05)
            rig.tick()
            if rig.message and rig.message not in seen:
                seen.append(rig.message)
        assert seen == ["BT: no conectado"], f"noisy retries: {seen}"


class TestScanningIsBlockedDuringPlayback:
    def test_entering_the_screen_does_not_scan_mid_hymn(self, bt_rig):
        rig = bt_rig()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        open_bluetooth(rig)
        assert not rig.bt.state().scanning

    def test_asking_for_a_scan_mid_hymn_is_refused(self, bt_rig):
        rig = bt_rig()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        open_bluetooth(rig)
        select(rig, "Buscar de nuevo")
        rig.press(Kind.CONFIRM)
        assert not rig.bt.state().scanning
        assert rig.message == "Detén el himno"

    def test_connecting_a_known_speaker_still_works_mid_hymn(self, bt_rig):
        rig = bt_rig(paired=(JBL,))
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        open_bluetooth(rig)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM, Kind.CONFIRM)
        rig.advance(5)
        assert rig.bt.state().connected_mac == JBL


class TestForgetting:
    def open_forget(self, rig):
        open_bluetooth(rig)
        select(rig, "JBL")
        rig.press(Kind.CONFIRM)                        # device screen
        while "Olvidar" not in (rig.cursor_row() or ""):
            rig.press(Kind.DOWN)
        return rig.press(Kind.CONFIRM)

    def test_it_asks_first_and_defaults_to_no(self, bt_rig):
        rig = bt_rig()
        vm = self.open_forget(rig)
        assert "Olvidar" in vm.status_left
        assert rig.cursor_row(vm) == "> No"

    def test_answering_no_changes_nothing(self, bt_rig):
        rig = bt_rig()
        self.open_forget(rig)
        rig.press(Kind.CONFIRM)
        rig.advance(2)
        assert rig.bt.state().device(JBL).paired

    def test_answering_yes_forgets_and_clears_the_boot_target(self, bt_rig):
        rig = bt_rig()
        rig.app.settings.last_bt_device = JBL
        self.open_forget(rig)
        rig.press(Kind.DOWN, Kind.CONFIRM)             # move to Sí, confirm
        rig.advance(2)
        device = rig.bt.state().device(JBL)
        assert device is None or not device.paired
        assert rig.app.settings.last_bt_device == ""


class TestTheTransportIsNeverHijacked:
    def test_play_and_seek_work_from_the_bluetooth_screen(self, bt_rig):
        rig = bt_rig()
        rig.type_number(5)
        rig.press(Kind.CONFIRM)
        open_bluetooth(rig)
        rig.press(Kind.PLAY_PAUSE)
        assert rig.player.paused
        rig.press(Kind.SEEK_BACK)
        assert rig.player.seeks
        assert rig.app.mode is Mode.BT_LIST
