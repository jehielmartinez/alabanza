"""Which sink the audio actually comes out of.

Connecting a Bluetooth speaker does not move audio to it — something has to
point mpv at the right sink. On the device that is PipeWire (Pi OS Lite ships
no sound server at all; see docs/BLUETOOTH.md), and "Salida" becomes mpv's
`audio-device` property.

Sink names vary per unit (which USB port the DAC landed in, which MAC the
speaker has), so the matching lives here and never reaches the state machine.
Nothing matches on a dev machine — mpv's macOS devices are `coreaudio/...` —
so development always falls through to mpv's own default.
"""

AUTO = "auto"

# (output, ordered substrings to look for in the mpv device name)
_RULES = {
    "jack": ("usb",),                    # the USB DAC is the headphone jack
    "hdmi": ("hdmi",),
    "bluetooth": ("bluez",),
}
_PREFIXES = ("pipewire/", "alsa/", "alsa_output.", "pulse/")


def _candidates(devices: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Only devices named the way the Pi's audio stack names them."""
    return [(name, desc) for name, desc in devices
            if any(name.startswith(p) or p in name for p in _PREFIXES)]


def resolve(devices: list[tuple[str, str]], output: str, bt_mac: str = "") -> str:
    """Pick the mpv `audio-device` for the selected output.

    `devices` is mpv's own audio-device-list as (name, description) pairs.
    Falls back to "auto" whenever nothing matches, which is both the dev-machine
    case and the safe answer on a device whose sink is missing.
    """
    pool = _candidates(devices)
    if not pool:
        return AUTO
    if output == "bluetooth" and bt_mac:
        # PipeWire names the sink after the MAC: bluez_output.AA_BB_CC_00_00_01
        tag = bt_mac.replace(":", "_").lower()
        for name, _ in pool:
            if tag in name.lower():
                return name
    for needle in _RULES.get(output, ()):
        for name, desc in pool:
            if needle in name.lower() or needle in desc.lower():
                return name
    return AUTO
