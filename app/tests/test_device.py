"""Smoke tests that need the real thing. Deselected everywhere but a Pi.

    uv run --extra test --extra device pytest -m device

These answer "is the hardware wired and configured?", not "is the logic
right" — the logic is covered off-device by everything else. Run them after
each peripheral is wired (Phase 1) and as the first step of the batch
acceptance check (Phase 5). See docs/TESTING.md.
"""

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.device


class TestTheDisplay:
    def test_the_i2c_bus_exists(self):
        import os
        assert os.path.exists("/dev/i2c-1"), "enable I2C with raspi-config"

    def test_the_oled_answers_at_its_address(self):
        """0x3C is the SSD1309; 0x36 alongside it is the UPS fuel gauge."""
        assert shutil.which("i2cdetect"), "apt install i2c-tools"
        out = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True,
                             text=True).stdout
        assert "3c" in out.lower(), f"no display on the bus:\n{out}"

    def test_a_frame_reaches_the_panel(self):
        from alabanza.display import ViewModel
        from alabanza.oled import OledDisplay
        OledDisplay().render(ViewModel(status_left="● Test", title="Himno: 001"))


class TestTheControls:
    """Wire one at a time and re-run; each failure names what is not wired."""

    PINS = {
        "keypad rows": (5, 6, 13, 19),
        "keypad columns": (12, 16, 20),
        "encoder A/B/push": (17, 27, 22),
        "d-pad centre": (23,),
        "d-pad left/right": (25, 26),
        "d-pad up/down": (7, 8),
    }

    def test_every_pin_in_the_map_can_be_claimed(self):
        from gpiozero import Button
        for name, pins in self.PINS.items():
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
        assert shutil.which("pactl"), "apt install pipewire pipewire-pulse"
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
        the writable partition or every pairing is lost. Phase 4."""
        import os
        path = "/var/lib/bluetooth"
        assert os.path.isdir(path)
        assert os.access(path, os.W_OK), \
            f"{path} is not writable — pairings will not survive a reboot"
