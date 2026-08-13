"""Which sink the audio comes out of.

Sink names differ per unit — which USB port the DAC landed in, which MAC the
speaker has — so this is the one place that guesses, and it must guess safely:
anything it does not recognise becomes "auto" rather than silence.
"""

from alabanza.audio import AUTO, resolve

# what `mpv --audio-device=help` looks like on the device
PI = [
    ("pipewire/alsa_output.usb-GeneralPlus_USB_Audio_Device-00.analog-stereo",
     "USB Audio Device"),
    ("pipewire/alsa_output.platform-107c701400.hdmi.hdmi-stereo", "HDMI"),
    ("pipewire/bluez_output.AA_BB_CC_00_00_01.1", "JBL Flip 5"),
    ("pipewire/auto_null", "Dummy Output"),
]
MAC = [("coreaudio/AppleHDA", "MacBook Pro Speakers"),
       ("coreaudio/usb-audio", "Some USB Interface")]


class TestOnTheDevice:
    def test_jack_finds_the_usb_dac(self):
        assert "usb-GeneralPlus" in resolve(PI, "jack")

    def test_hdmi_finds_the_hdmi_sink(self):
        assert "hdmi" in resolve(PI, "hdmi")

    def test_bluetooth_finds_the_sink_for_that_speaker(self):
        assert resolve(PI, "bluetooth", "AA:BB:CC:00:00:01") == \
            "pipewire/bluez_output.AA_BB_CC_00_00_01.1"

    def test_a_different_speaker_is_not_mistaken_for_the_connected_one(self):
        # falls back to the generic bluez rule, not the wrong MAC's sink
        assert resolve(PI, "bluetooth", "FF:FF:FF:FF:FF:FF").startswith("pipewire/bluez")


class TestOffTheDevice:
    def test_a_dev_machine_falls_through_to_mpv_default(self):
        """coreaudio names must never match, or dev would grab a random sink."""
        for output in ("jack", "hdmi", "bluetooth"):
            assert resolve(MAC, output) == AUTO

    def test_an_empty_device_list_is_auto(self):
        assert resolve([], "jack") == AUTO


class TestWhenTheSinkIsMissing:
    def test_bluetooth_with_no_speaker_connected_is_auto(self):
        without_bt = [d for d in PI if "bluez" not in d[0]]
        assert resolve(without_bt, "bluetooth") == AUTO

    def test_an_unknown_output_name_is_auto_not_a_crash(self):
        assert resolve(PI, "carrier-pigeon") == AUTO
