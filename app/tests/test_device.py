"""Smoke tests that need the real thing. Deselected everywhere but a Pi.

    uv run --extra test --extra device pytest -m device

These answer "is the hardware wired and configured?", not "is the logic
right" — the logic is covered off-device by everything else. Run them after
each peripheral is wired (Phase 1) and as the first step of the batch
acceptance check (Phase 5). See docs/TESTING.md.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.device


class TestTheDisplay:
    def test_the_i2c_bus_exists(self):
        import os
        assert os.path.exists("/dev/i2c-1"), "enable I2C with raspi-config"

    def test_the_oled_answers_at_its_address(self):
        """0x3C is the SSD1309; 0x36 alongside it is the UPS fuel gauge."""
        # i2cdetect lives in /usr/sbin, which is not on PATH for a
        # non-login shell — so `ssh pi pytest` cannot find a tool that is
        # perfectly well installed. Look there explicitly.
        exe = shutil.which("i2cdetect", path="/usr/sbin:/usr/bin:/bin")
        assert exe, "apt install i2c-tools"
        out = subprocess.run([exe, "-y", "1"], capture_output=True,
                             text=True).stdout
        assert "3c" in out.lower(), f"no display on the bus:\n{out}"

    def test_a_frame_reaches_the_panel(self):
        from alabanza.display import ViewModel
        from alabanza.oled import OledDisplay
        OledDisplay().render(ViewModel(status_left="● Test", title="Himno: 001"))


class TestTheControls:
    """Wire one at a time and re-run; each failure names what is not wired."""

    def test_every_pin_in_the_map_can_be_claimed(self):
        from gpiozero import Button

        from alabanza.pins import CONTROLS
        for name, pins in CONTROLS.items():
            for pin in pins:
                try:
                    Button(pin, pull_up=True).close()
                except Exception as exc:            # noqa: BLE001 - report which
                    pytest.fail(f"{name} pin {pin}: {exc}")


class TestAudio:
    def test_the_usb_dac_is_present(self):
        from alabanza.audio import AUTO, resolve
        from alabanza.player import Player
        player = Player(video=False)
        try:
            assert resolve(player.audio_devices, "jack") != AUTO, \
                "no USB DAC found; check the OTG adapter"
        finally:
            player.shutdown()

    def test_pipewire_is_running(self):
        # pactl comes from pulseaudio-utils, not from pipewire-pulse: the
        # latter is the server side of the protocol and ships no client.
        assert shutil.which("pactl"), \
            "apt install pipewire pipewire-pulse wireplumber pulseaudio-utils"
        out = subprocess.run(["pactl", "info"], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr


class TestBluetooth:
    def test_the_adapter_is_present_and_powered(self):
        from alabanza.bt_bluez import BluezBackend
        backend = BluezBackend()
        try:
            assert backend.state().available, "no adapter, or rfkill blocked"
        finally:
            backend.close()

    def test_pairings_survive_a_reboot(self):
        """Under a read-only root, /var/lib/bluetooth must be bind-mounted to
        the writable partition or every pairing is lost. Phase 4.

        The check is on the *filesystem*, not on our own permissions: the
        directory is 0700 root:root because BlueZ runs as root, so asking
        whether the invoking user can write to it answers a different
        question and fails on a perfectly good device.
        """
        import os
        path = "/var/lib/bluetooth"
        assert os.path.isdir(path)

        mount, options = "", []
        with open("/proc/mounts") as mounts:
            for line in mounts:
                _, point, _, opts, *_ = line.split()
                if (point == path or path.startswith(point.rstrip("/") + "/")) \
                        and len(point) > len(mount):
                    mount, options = point, opts.split(",")

        assert "ro" not in options, (
            f"{path} sits on {mount}, mounted read-only — pairings will not "
            "survive a reboot. Bind-mount it onto the writable partition.")


class TestPlaybackStartsWhenAsked:
    """mpv is asynchronous and the app is not. Only real libmpv shows this,
    so it cannot live in the laptop suite."""

    def test_a_hymn_counts_as_active_the_instant_play_returns(self, tmp_path):
        """play() returns in ~1 ms; mpv sets `filename` ~12 ms later.

        app.tick() runs microseconds after app.handle(), so it lands inside
        that window. When `active` reported False there, tick() concluded the
        hymn had finished on its own, cleared it and put the idle image back
        over a hymn that had only just started — and the operator saw their
        keypress do nothing.
        """
        from alabanza.player import Player

        media = next(iter(sorted(
            (Path.home() / "alabanza" / "tools" / "library").glob("*.mp4"))), None)
        if media is None:
            pytest.skip("no library on this device")

        player = Player(video=False)
        try:
            player.play(media)
            assert player.active, (
                "a hymn is not 'active' immediately after play() — tick() will "
                "read it as finished and cancel it")
        finally:
            player.shutdown()

    def test_the_idle_image_is_not_mistaken_for_a_hymn(self):
        """The reverse error: the image is loaded through the same mpv, so
        `active` must exclude it or Stop and Play act on a picture."""
        from alabanza.player import Player

        player = Player(video=False)
        try:
            player.show_idle()
            assert not player.active
        finally:
            player.shutdown()
