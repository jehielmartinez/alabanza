# Alabanza — Hymn Player

> **Status: AGREED DRAFT v1** — decisions below confirmed through spec interview on 2026-08-12. A few minor open questions remain at the bottom.

A Raspberry Pi–based media appliance whose sole purpose is playing hymns at a local church. Turn it on, pick a hymn by number, play it. Operated entirely through an OLED display and physical controls — no keyboard, mouse, network, or SSH in day-to-day use.

## Hardware

Production target: **10 units**, cost-optimized. The library turned out to be 720p H.264 (2.2 GB total), which the Pi Zero 2 W hardware-decodes — the original Pi 4 choice is no longer necessary. Measured with `ffprobe` across the real files: every clip is 720 high, widths vary with aspect ratio (1152, 1280, 960, 1168), audio is AAC 128 kbps 44.1 kHz throughout.

| Part | Choice | Why |
|---|---|---|
| Computer | Raspberry Pi Zero 2 WH | $15; decodes the 720p H.264 library in hardware; built-in Bluetooth; ~2 W draw halves the battery. WH = pre-soldered header |
| Audio out (jack) | USB audio adapter + micro-USB OTG adapter | Zero 2 W has no analog jack; a USB DAC (~$8) is cleaner than the Pi 4's analog out anyway |
| Video out | mini-HDMI → HDMI adapter | Zero 2 W uses mini-HDMI |
| Display | 2.42" SSD1309 OLED, 128×64 | Readable at a glance in a dim room, including for older eyes; same driver family as smaller modules |
| Keypad | 3×4 matrix (0–9, *, #) | Digit entry, and letters for predictive T9 search. No A–D column: nothing needs it |
| Buttons | A 5-way **D-pad**: ◀ ▶ ▲ ▼ + centre | One familiar part instead of seven loose buttons. ◀▶ seek, ▲▼ adjust, centre plays/pauses |
| Encoder | Rotary with push button | Wheel = volume while playing, browse the hymn numbers while idle. Push = menu |
| Storage | 32 GB microSD | OS + app + the 2.1 GB library, with margin |
| Battery | 2×18650 UPS board (~25 Wh), I2C fuel gauge | 8h+ playback at ~2 W draw; charges in place; usable while charging |

Prototyping continues on a Pi 4 Model B (same BCM2711 generation, same hardware H.264 decode, same GPIO block, same OS image — see [BUILD-PLAN.md](BUILD-PLAN.md)). **Before committing to 10 boards, one Zero 2 W is bought first** to validate video, Bluetooth, and USB audio on real hardware.

## Library

- **517 hymns, MP4 only.** The MP3s duplicate the same recordings and are dropped. One canonical file per hymn number.
- Lives on the **SD card, read-only partition**, loaded once at provisioning. Content is not expected to change; rare updates happen offline with a card reader.
- Provisioning builds a **number → title → file index** (from filenames or a generated manifest); runtime never parses filenames.
- When no HDMI is connected, playback is audio-only (video decode suppressed).

## Controls

Nineteen inputs, and **every function reachable with one press** — no chords, no
long-presses, nothing hidden, with exactly one exception (shutdown, below). Fewer controls is a hard goal, not a preference:
each one is a panel cutout ×10 units and a line on the laminated card.

| Control | Home screen | List screens (menu, Bluetooth, search) |
|---|---|---|
| `0`–`9` | hymn number | T9 letters, in search — one press per letter |
| `*` | erase a digit — or, with nothing typed, **stop** | back / cancel |
| `#` | play the selection | confirm |
| D-pad centre | play / pause | play / pause (menus never take the transport) |
| D-pad ◀ ▶ | seek | seek |
| D-pad ▲ ▼ | **speed** while playing, browse while idle (▲ = higher number) | move the cursor |
| Wheel | **volume** while playing, browse while idle (clockwise = higher number) | move the cursor |
| Push | **menu** | select |
| Push, held 3 s | **power off** | power off |

Four functions have no button of their own and are none the worse: Stop is `*`
("clear what is going on"), Speed is ▲▼ *while a hymn plays* — exactly when it
is wanted — the Menu is the encoder push, and T9 search is a menu entry, since
the spec already makes it the secondary path to a hymn.

The one thing given up: browsing the list while a hymn plays, because ▲▼ are the
speed then. Typing the next number still works during playback, which is the
way an operator queues the next hymn anyway.

## Selection

1. **Primary: direct number entry.** Operator types the hymn number; OLED live-updates with number + title; Play or `#` confirms and starts playback.
2. **Secondary: browse + search.** Scrollable title list (D-pad ▲▼ or the wheel) with T9 title search on the keypad, reached from the menu, for when the number isn't known.

   **Predictive T9, one press per letter** — not multi-tap. `Cielo` is
   `2 4 3 5 6`, five presses. Titles are matched by converting each word to
   its digit sequence, so the list filters from the first key and narrows as
   you type; the operator reads the results, not the digits.

   Multi-tap was the original wording here and was rejected once the two were
   compared on hardware. `Cielo` becomes `2 444 33 555 666` — twelve presses
   on a panel whose whole design goal is fewer of them — and same-key letters
   need a timeout between them, which is precisely the interaction an older
   volunteer gets wrong: a pause slightly too short silently yields the wrong
   letter, with no way to tell why.

## Playback

- **Engine**: mpv (libmpv). One engine for video, audio-only, seek, pause, speed.
- **Speed**: pitch-preserved time-stretch (`scaletempo2`), **75%–125% in 5% steps**, on the D-pad's ▲▼ while a hymn plays. Key never changes — safe for singalong. Shown on OLED. **Resets to 100% on each new hymn.**
- **Seek**: D-pad ◀/▶ step through the track (default step: 10 s; held = repeat).
- **Volume**: the encoder wheel while a hymn plays, 1% per click; while idle the wheel browses the hymn numbers instead. **Persisted per output** (Jack / BT / HDMI each remember their own level) so switching outputs never produces a surprise.

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
- **Integrated UPS board with 2×18650 cells** inside the enclosure: 5 V output, **true power-path charging** (device fully usable while plugged in and charging), charges from a wall adapter. Power-path is a hard requirement, not a nice-to-have — see decision 19; a plain Li-ion charger cannot provide it.
- The board's **I2C fuel gauge** feeds the app: battery percentage is always visible on the OLED status line; charging state shown when plugged in. *(Product stage — deferred on the prototype, see decision 21.)*
- **Low battery**: warning on OLED at 15%, **safe automatic shutdown at ~5%** — the device never brownout-crashes mid-hymn. *(Product stage — deferred on the prototype, see decision 21.)*
- **Yank-safe by design**: root filesystem read-only (overlay mode). Settings (volumes, paired speakers, selected output) live on a tiny writable partition with rare, atomic writes.
- Unplugging or hard power-off at any moment is **officially supported**.
- **Shutdown has two routes**: `Apagar`, the last item in the menu, and
  **holding the encoder push for 3 seconds** — the OLED counts down from
  0.6 s so there is time to let go, and going dark is how the panel says it
  worked.

  The hold is the **one deliberate exception** to "no long-presses" above.
  Every other control should be instant; this single one must be hard to do
  by accident, and a hold is self-cancelling in a way a menu item is not —
  let go and nothing happened. Both routes exist because a hold is
  undiscoverable and a menu is slow, and shutdown wants to be neither.

- **Turning it back on is a separate, recessed button** wired to the Pi's RUN
  pads. On battery there is no plug to pull, so shutdown needed an inverse and
  did not have one. It cannot be a panel control: see decision 23.

## Software stack

- **OS**: Raspberry Pi OS Lite (64-bit), no desktop. Video renders via DRM/KMS directly — this is what makes "nothing but the video" easy and boot fast (~10–15 s to ready).
- **App**: Python 3, single systemd service, structured as a state machine reacting to input events.
- **Key libraries**: `python-mpv` (playback), `luma.oled` (SSD1309), `gpiozero` (keypad, buttons, encoder), BlueZ over D-Bus via `dbus-fast` (Bluetooth — see [BLUETOOTH.md](BLUETOOTH.md)).

## Open questions (minor, non-blocking)

1. **Source file naming**: are the 517 MP4s already named with hymn numbers, or is a one-time rename/manifest script needed at provisioning? (Script is trivial either way.)
2. **Everyday output default**: which path is the normal Sunday setup — jack into a mixer/PA, Bluetooth speaker, or TV via HDMI? Affects the factory-default output selection only.
3. **Enclosure**: case/panel design for Pi + OLED + keypad + encoder + buttons — deferred until the electronics are proven on a breadboard.
4. **Power supply**: official 5 V/3 A USB-C supply assumed.

## Decision log

1. **Hardware: Raspberry Pi 4** — only model covering every requirement natively.
2. **Library format: MP4 only** — MP3s are the same recordings; dropped.
3. **Selection: number entry first; browse + title search fallback.**
4. **Controls: 3×4 keypad + 5-way D-pad + rotary encoder** (supersedes the
   original 4×4-plus-seven-buttons plan). 19 inputs, every function one press
   away. A D-pad is one familiar, cheap part where seven panel-mount buttons
   were seven cutouts and seven chances to mislabel; ◀▶ = seek and centre =
   play are conventions nobody has to be taught. Dropped along the way: the
   A–D keypad column, and the dedicated Stop, Speed ± and Menu buttons.
5. **Audio routing: explicit persisted menu choice; never auto-switches; pause + warn on output loss.**
6. **Volume: rotary during playback, 1% per click; per-output memory.** While idle the same wheel browses the hymn numbers, clockwise upwards — an earlier draft said "volume, always", and the first demo on the bench showed the operator reaching for the knob to browse.
7. **Speed: pitch-preserved, 75–125% in 5% steps; resets per hymn.**
8. **HDMI states: image on boot/idle/stop, clean fullscreen video when playing, freeze-frame on pause.**
9. **Bluetooth: remember all paired; auto-reconnect last-used only when BT is the selected output.**
10. **Power: read-only FS, yank-safe; menu shutdown also available.**
11. **Library home: SD card, effectively immutable; index built at provisioning.**
12. **Display: 2.42" SSD1309 128×64 OLED.**
13. **Stack: Pi OS Lite + Python 3 + libmpv; luma.oled, gpiozero, BlueZ/D-Bus.**
14. **Battery scenario: fully portable, 8h+ playback** — runs unplugged as the norm (e.g. services away from an outlet), not just outage-bridging.
15. **Battery hardware: integrated 18650 UPS board** with I2C fuel gauge — OLED battery %, 15% warning, safe shutdown at ~5%, charge-while-playing.
16. **Production: 10 units on Pi Zero 2 WH** (supersedes decision 1's Pi 4). Justified by the real library being 720p H.264 — well inside the Zero 2 W's 1080p30 hardware decoder (earlier drafts of this document said 480p; `ffprobe` on the provisioned files says 720p, and the conclusion is unchanged) — and ~$50/unit savings across 10 units. Jack audio via USB DAC; battery re-specced to 2×18650 (~25 Wh) thanks to ~2 W draw. One unit is validated end-to-end before the batch order.
17. **Microcontroller alternative considered and rejected.** An ESP32 + MP3-decoder build (~$65/unit, instant-on, weeks of battery) was evaluated; rejected because it drops HDMI lyrics video entirely and degrades Bluetooth reliability — both core features. Video output stays via the Zero 2 W's mini-HDMI (panel-mount mini-HDMI→HDMI extension on the enclosure, ~$7).

18. **Single custom control PCB that is also the front panel** (supersedes the
    protoboard-hat idea in BUILD-PLAN Phase 5). Keypad, D-pad, encoder and OLED
    on the front; Pi Zero 2 WH socketed on the back and powered through the
    header. Chosen because every control has to reach the panel anyway — a
    Pi-stacked board would need ~22 hand-run wires per unit, which is the exact
    thing the PCB exists to remove. Design and pre-fab checklist in
    [HARDWARE.md](HARDWARE.md).
19. **TP4056 charger evaluated and rejected as the power source.** Three modules
    were bought before the gap was spotted: the TP4056 is a single-cell charger,
    not a UPS. It provides no 5 V (outputs raw 2.5–4.2 V cell voltage), no load
    sharing (so the device cannot run while charging — a stated requirement),
    and no I2C fuel gauge (so no battery %, no 15% warning, no safe shutdown).
    Building the missing pieces around it means a boost converter, an
    ideal-diode load-share circuit and a separate MAX17048 — three chances to
    get analogue design wrong on a board whose digital half is already
    validated. Decision: buy an integrated UPS module meeting the requirements
    in [HARDWARE.md](HARDWARE.md), and keep the TP4056s as bench cell chargers.
20. **Prototype power: a PB0063A LiPo charger/boost module + LiPo battery, with
    no battery gauge.** Deliberate scope reduction for the first board. A survey
    found no module meeting all six power requirements at once — the Pi Zero
    market offers ~1200 mAh handheld packs or large HATs for the Pi 4/5, and
    every option assumes a free GPIO header, which decision 18 made false.
    Rejected: PowerBoost 1000C (1 A ceiling, no gauge), Waveshare UPS HAT (C)
    (HAT form factor, micro-USB), PiSugar S (~4.4 Wh ≈ 2 h, no I2C),
    Pi-Ener-lite (~12 Wh, pogo pins, single-vendor supply), IP5306 modules (no
    I2C of any kind). Gauging would have needed a second module (MAX17048 @
    0x36), and it is the one function not required to prove the device works.
21. **Battery percentage, the 15% warning and the 5% shutdown are product-stage
    features, not prototype features** (narrows decision 15). The read-only root
    filesystem already makes abrupt power loss a non-event (decision 10), so the
    prototype runs until it stops. They return when the power block is
    integrated onto the main board — where a single PMU IC (X-Powers AXP2101
    class, as used in ClockworkPi's PicoCalc) provides charger, power path,
    regulation and fuel gauge in one part. This is why no vendor sells the
    all-in-one module: products design the PMU onto the mainboard.

22. **Shutdown is a menu item and a 3-second hold on the encoder push, and the
    app never quits to a console.** The menu previously offered "Salir", which
    exited the process — wrong in both directions on an appliance: it drops the
    projector to a Linux console, which decision 8 forbids, or systemd silently
    restarts it. The hold breaks "no chords, no long-presses, nothing hidden"
    on purpose and is the only thing that does: shutdown is the single action
    where being hard to trigger by accident beats being quick, and a hold is
    self-cancelling in a way a menu item is not. Both routes exist because a
    hold is undiscoverable and a menu is slow. The device runs as a systemd
    **user** service — it needs the user's PipeWire session for audio, which a
    system service would not have — and is granted exactly one privilege,
    `/sbin/poweroff`, via a sudoers drop-in.

23. **Power-on is a dedicated recessed button on the Pi's RUN pads, not a
    panel control.** Shutdown had no inverse. Mains-powered that is invisible
    — you pull the plug — but the device is battery powered, so a unit shut
    down in a cupboard had no way back short of opening the case.

    It cannot be one of the existing controls, and that is a hardware fact
    rather than a preference. `poweroff` halts the SoC: no kernel, no app,
    nothing polling, so a button on any of the spare GPIOs is read by nobody.
    Only two inputs start a halted Pi, and neither is software reading a pin
    — **GPIO3**, which the boot firmware treats as wake-from-halt, and
    **RUN**, the SoC reset line. GPIO3 is already SCL for the OLED and the
    reserved `0x36` gauge; a button shorting it to ground mid-frame would
    stall the I2C bus.

    So RUN, with its own switch. It cannot share the encoder push: RUN is
    live whenever the board is powered, so every press meant to open the menu
    would hard-reset the device mid-hymn. That also fixes the placement —
    recessed or on the back, never beside the keypad — because a press while
    running *is* a power yank, which decision 10 makes survivable but not
    pleasant.

    It works because `poweroff` leaves the board halted while the power module
    keeps the 5 V rail up: RUN resets the SoC, the bootloader runs again, and
    it boots. The corollary is that this is prototype-stage by nature. A
    halted Zero still draws tens of milliamps, so "off" flattens a battery
    over days — fine between services, not for storage. The product answer is
    a soft-latch that cuts the rail entirely, at which point RUN has no power
    to release and the latch button takes over both directions. Deferred with
    the integrated power block (decision 21), so the asymmetry — hold the
    encoder to stop, press the recessed button to start — is v1's, and one
    line on the laminated card covers it.
