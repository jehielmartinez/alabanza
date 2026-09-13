"""The kernel-input backend's logic, off-device.

The thread and the descriptors need a Pi with the overlays loaded; the rules
-- what a press, a hold and a wheel step become, and how bounce is ignored --
are pure and live in KeyLogic, so they are pinned down here.
"""

import struct

from alabanza.events import Event, Kind
from alabanza.input_evdev import (
    EV_KEY,
    EV_REL,
    HELD_REPEAT,
    KEY_ENTER,
    KEY_LEFT,
    KEY_MENU,
    KEY_UP,
    REL_X,
    SEEK_REPEAT,
    KeyLogic,
    _has_bit,
    decode,
)


def press(logic, code, now):
    return logic.feed(EV_KEY, code, 1, now)


def release(logic, code, now):
    return logic.feed(EV_KEY, code, 0, now)


class TestPressesBecomeEvents:
    def test_a_press_is_its_kind_and_a_release_is_silent(self):
        logic = KeyLogic()
        assert press(logic, KEY_ENTER, 1.0) == [Event(Kind.PLAY_PAUSE)]
        assert release(logic, KEY_ENTER, 1.2) == []
        assert logic.due(9.0) == [], "a plain key owes nothing while held"

    def test_the_kernels_own_autorepeat_is_ignored(self):
        """Repeat timing is ours, so the two never stack."""
        logic = KeyLogic()
        press(logic, KEY_UP, 1.0)
        assert logic.feed(EV_KEY, KEY_UP, 2, 1.3) == []

    def test_codes_the_device_does_not_use_are_dropped(self):
        assert KeyLogic().feed(EV_KEY, 999, 1, 1.0) == []


class TestBounce:
    def test_a_second_edge_within_the_window_is_ignored(self):
        logic = KeyLogic()
        assert press(logic, KEY_ENTER, 1.000) == [Event(Kind.PLAY_PAUSE)]
        assert release(logic, KEY_ENTER, 1.005) == []
        assert press(logic, KEY_ENTER, 1.010) == [], "contact bounce, not a second press"
        assert press(logic, KEY_ENTER, 1.100) == [Event(Kind.PLAY_PAUSE)]


class TestSeekRepeats:
    def test_a_held_seek_key_repeats_at_the_interval(self):
        logic = KeyLogic()
        assert press(logic, KEY_LEFT, 0.0) == [Event(Kind.SEEK_BACK)]
        assert logic.due(SEEK_REPEAT - 0.01) == []
        assert logic.due(SEEK_REPEAT) == [Event(Kind.SEEK_BACK)]
        assert logic.due(SEEK_REPEAT + 0.1) == []
        assert logic.due(2 * SEEK_REPEAT) == [Event(Kind.SEEK_BACK)]
        release(logic, KEY_LEFT, 2 * SEEK_REPEAT + 0.05)
        assert logic.due(10.0) == [], "released keys stop repeating"

    def test_next_due_tells_the_thread_how_long_to_sleep(self):
        logic = KeyLogic()
        assert logic.next_due(0.0) is None
        press(logic, KEY_LEFT, 0.0)
        assert abs(logic.next_due(0.1) - (SEEK_REPEAT - 0.1)) < 1e-9
        assert logic.next_due(5.0) == 0.0, "overdue is due now, never negative"


class TestTheEncoderPush:
    def test_push_keepalives_then_release(self):
        logic = KeyLogic()
        assert press(logic, KEY_MENU, 0.0) == [Event(Kind.PUSH)]
        assert logic.due(HELD_REPEAT) == [Event(Kind.PUSH_HELD)]
        assert logic.due(2 * HELD_REPEAT) == [Event(Kind.PUSH_HELD)]
        assert release(logic, KEY_MENU, 0.6) == [Event(Kind.PUSH_RELEASE)]
        assert logic.due(10.0) == []


class TestTheWheel:
    def test_steps_become_one_event_each_with_the_sign_deciding_direction(self):
        logic = KeyLogic(wheel_sign=1)
        assert logic.feed(EV_REL, REL_X, 1, 0.0) == [Event(Kind.WHEEL_CW)]
        assert logic.feed(EV_REL, REL_X, -2, 0.0) == [Event(Kind.WHEEL_CCW)] * 2

    def test_the_sign_can_be_flipped_for_a_swapped_a_b(self):
        logic = KeyLogic(wheel_sign=-1)
        assert logic.feed(EV_REL, REL_X, 1, 0.0) == [Event(Kind.WHEEL_CCW)]


class TestRecords:
    def test_decode_splits_a_read_into_records(self):
        fmt = struct.Struct("llHHi")
        data = fmt.pack(0, 0, EV_KEY, KEY_UP, 1) + fmt.pack(0, 0, EV_REL, REL_X, -1)
        assert list(decode(data)) == [(EV_KEY, KEY_UP, 1), (EV_REL, REL_X, -1)]

    def test_a_partial_trailing_record_is_ignored(self):
        fmt = struct.Struct("llHHi")
        data = fmt.pack(0, 0, EV_KEY, KEY_UP, 1) + b"\x00" * 5
        assert list(decode(data)) == [(EV_KEY, KEY_UP, 1)]


class TestCapabilityMasks:
    """sysfs prints the bitmask as hex words, most significant first."""

    def test_low_bits_live_in_the_last_word(self):
        assert _has_bit("1", 0)
        assert _has_bit("10000000", 28)          # KEY_ENTER on a 32-bit word
        assert not _has_bit("10000000", 27)

    def test_high_bits_live_in_earlier_words(self):
        # 32-bit words: bit 103 is word 3, bit 7; bit 139 is word 4, bit 11.
        assert _has_bit("800 80 0 0 0", 139)
        assert _has_bit("800 80 0 0 0", 103)
        assert not _has_bit("0 0 0 0", 103)
        assert not _has_bit("", 0)
