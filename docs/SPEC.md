# Alabanza — Hymn Player

> **Status: AGREED DRAFT v1** — decisions below confirmed through spec interview on 2026-08-12. A few minor open questions remain at the bottom.

A Raspberry Pi–based media appliance whose sole purpose is playing hymns at a local church. Turn it on, pick a hymn by number, play it. Operated entirely through an OLED display and physical controls — no keyboard, mouse, network, or SSH in day-to-day use.

## Hardware

Production target: **10 units**, cost-optimized. The library turned out to be 480p H.264 (2.1 GB total), which the Pi Zero 2 W hardware-decodes — the original Pi 4 choice is no longer necessary.

| Part | Choice | Why |
|---|---|---|
| Computer | Raspberry Pi Zero 2 WH | $15; decodes the 480p H.264 library in hardware; built-in Bluetooth; ~2 W draw halves the battery. WH = pre-soldered header |
| Audio out (jack) | USB audio adapter + micro-USB OTG adapter | Zero 2 W has no analog jack; a USB DAC (~$8) is cleaner than the Pi 4's analog out anyway |
| Video out | mini-HDMI → HDMI adapter | Zero 2 W uses mini-HDMI |
| Display | 2.42" SSD1309 OLED, 128×64 | Readable at a glance in a dim room, including for older eyes; same driver family as smaller modules |
| Keypad | 4×4 matrix (0–9, *, #, A–D) | Digit entry + T9-style search |
| Encoder | Rotary with push button | List/menu scrolling; volume during playback |
| Buttons | Dedicated: Play/Pause, Stop, Seek ◀, Seek ▶, Speed −, Speed +, Menu/Back | Transport must be single-press, eyes-free, unambiguous in live use |
| Storage | 32 GB microSD | OS + app + the 2.1 GB library, with margin |
| Battery | 2×18650 UPS board (~25 Wh), I2C fuel gauge | 8h+ playback at ~2 W draw; charges in place; usable while charging |

Prototyping continues on the Pi 400 (same architecture, same OS image). **Before committing to 10 boards, one Zero 2 W is bought first** to validate video, Bluetooth, and USB audio on real hardware.

## Library

- **517 hymns, MP4 only.** The MP3s duplicate the same recordings and are dropped. One canonical file per hymn number.
- Lives on the **SD card, read-only partition**, loaded once at provisioning. Content is not expected to change; rare updates happen offline with a card reader.
- Provisioning builds a **number → title → file index** (from filenames or a generated manifest); runtime never parses filenames.
- When no HDMI is connected, playback is audio-only (video decode suppressed).

## Selection

1. **Primary: direct number entry.** Operator types the hymn number; OLED live-updates with number + title; Play or `#` confirms and starts playback.
2. **Secondary: browse + search.** Scrollable title list (rotary encoder) with T9 multi-tap title search on the keypad, for when the number isn't known.

## Playback

- **Engine**: mpv (libmpv). One engine for video, audio-only, seek, pause, speed.
- **Speed**: pitch-preserved time-stretch (`scaletempo2`), **75%–125% in 5% steps**. Key never changes — safe for singalong. Shown on OLED. **Resets to 100% on each new hymn.**
- **Seek**: ◀/▶ buttons step through the track (default step: 10 s; held = repeat).
- **Volume**: rotary encoder during playback. **Persisted per output** (Jack / BT / HDMI each remember their own level) so switching outputs never produces a surprise.

## Audio routing

- Output is an **explicit menu choice** — Jack / Bluetooth / HDMI — persisted across reboots and always visible on the OLED status line.
- The device **never auto-switches** outputs. Plugging HDMI changes video only.
- **Video and audio are independent.** Video always plays on HDMI when connected, regardless of the audio setting. The two everyday setups are both just `Salida` choices:
  - *Projector + church speakers*: Salida = Bluetooth (or Jack into the mixer) → video on the projector, audio through the speakers.
  - *TV*: Salida = HDMI → picture and sound through the one cable.
- If the selected output disappears (e.g. BT speaker dies): **pause + warn** on OLED. No silent fallback.

## Bluetooth

- Fully managed from OLED + controls: **Scan / Pair / Connect / Disconnect / Forget**.
- All paired speakers are remembered.
- **Auto-reconnect at boot to the last-used speaker — only when Bluetooth is the selected output.**
- Failed reconnect → `BT: not connected` on OLED; pressing Play warns instead of playing into the void.

## HDMI screen states

The projector/TV shows **only** these — no desktop, console, overlays, progress bars, or UI chrome, ever. All status lives on the OLED.

| State | Screen shows |
|---|---|
| Boot | Static image (quiet boot: no console text, no rainbow splash) |
| Idle / stopped | Static image |
| Playing | Fullscreen video, zero overlays |
| Paused | Freeze-frame |
| Hymn ends | Cut back to static image |

The static image is a replaceable file (`screensaver.png`) with a built-in fallback.

## Power & robustness

- **Battery powered and rechargeable — fully portable.** Target: **8+ hours of playback** unplugged (Zero 2 W averages ~2 W playing media → ~20 Wh needed, 2×18650 ≈ 25 Wh provides it).
- **Integrated UPS board with 2×18650 cells** inside the enclosure: 5 V output, power-path charging (device fully usable while plugged in and charging), charges from a wall adapter.
- The board's **I2C fuel gauge** feeds the app: battery percentage is always visible on the OLED status line; charging state shown when plugged in.
- **Low battery**: warning on OLED at 15%, **safe automatic shutdown at ~5%** — the device never brownout-crashes mid-hymn.
- **Yank-safe by design**: root filesystem read-only (overlay mode). Settings (volumes, paired speakers, selected output) live on a tiny writable partition with rare, atomic writes.
- Unplugging or hard power-off at any moment is **officially supported**. A menu Shutdown option also exists for the tidy-minded.

## Software stack

- **OS**: Raspberry Pi OS Lite (64-bit), no desktop. Video renders via DRM/KMS directly — this is what makes "nothing but the video" easy and boot fast (~10–15 s to ready).
- **App**: Python 3, single systemd service, structured as a state machine reacting to input events.
- **Key libraries**: `python-mpv` (playback), `luma.oled` (SSD1309), `gpiozero` (keypad, buttons, encoder), BlueZ over D-Bus (Bluetooth).

## Open questions (minor, non-blocking)

1. **Source file naming**: are the 517 MP4s already named with hymn numbers, or is a one-time rename/manifest script needed at provisioning? (Script is trivial either way.)
2. **Everyday output default**: which path is the normal Sunday setup — jack into a mixer/PA, Bluetooth speaker, or TV via HDMI? Affects the factory-default output selection only.
3. **Enclosure**: case/panel design for Pi + OLED + keypad + encoder + buttons — deferred until the electronics are proven on a breadboard.
4. **Power supply**: official 5 V/3 A USB-C supply assumed.

## Decision log

1. **Hardware: Raspberry Pi 4** — only model covering every requirement natively.
2. **Library format: MP4 only** — MP3s are the same recordings; dropped.
3. **Selection: number entry first; browse + title search fallback.**
4. **Controls: 4×4 keypad + rotary encoder + dedicated transport buttons.**
5. **Audio routing: explicit persisted menu choice; never auto-switches; pause + warn on output loss.**
6. **Volume: rotary during playback; per-output memory.**
7. **Speed: pitch-preserved, 75–125% in 5% steps; resets per hymn.**
8. **HDMI states: image on boot/idle/stop, clean fullscreen video when playing, freeze-frame on pause.**
9. **Bluetooth: remember all paired; auto-reconnect last-used only when BT is the selected output.**
10. **Power: read-only FS, yank-safe; menu shutdown also available.**
11. **Library home: SD card, effectively immutable; index built at provisioning.**
12. **Display: 2.42" SSD1309 128×64 OLED.**
13. **Stack: Pi OS Lite + Python 3 + libmpv; luma.oled, gpiozero, BlueZ/D-Bus.**
14. **Battery scenario: fully portable, 8h+ playback** — runs unplugged as the norm (e.g. services away from an outlet), not just outage-bridging.
15. **Battery hardware: integrated 18650 UPS board** with I2C fuel gauge — OLED battery %, 15% warning, safe shutdown at ~5%, charge-while-playing.
16. **Production: 10 units on Pi Zero 2 WH** (supersedes decision 1's Pi 4). Justified by the real library being 480p H.264 (hardware-decoded by the Zero 2 W) and ~$50/unit savings across 10 units. Jack audio via USB DAC; battery re-specced to 2×18650 (~25 Wh) thanks to ~2 W draw. One unit is validated end-to-end before the batch order.
17. **Microcontroller alternative considered and rejected.** An ESP32 + MP3-decoder build (~$65/unit, instant-on, weeks of battery) was evaluated; rejected because it drops HDMI lyrics video entirely and degrades Bluetooth reliability — both core features. Video output stays via the Zero 2 W's mini-HDMI (panel-mount mini-HDMI→HDMI extension on the enclosure, ~$7).
