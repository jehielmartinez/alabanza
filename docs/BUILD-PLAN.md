# Alabanza — Build Plan

Companion to [SPEC.md](SPEC.md). The spec says *what* the device is; this says *how and in what order* it gets built.

**Bottom line**: playable bench prototype in 2–3 weekends after parts arrive; finished boxed device in 6–10 weeks at hobby pace. Production target: **10 units** at ≈ **$110–130/unit**.

## Per-unit shopping list (Pi Zero 2 W build)

| # | Part | Spec | Est. price | Notes |
|---|------|------|-----------|-------|
| 1 | Raspberry Pi Zero 2 **WH** | pre-soldered header | ~$18 | Hardware-decodes the 480p H.264 library. WH saves soldering 40 pins ×10 units |
| 2 | USB audio adapter | USB-A DAC with 3.5mm out + micro-USB OTG adapter | ~$10 | The "headphone jack". Buy one known-good model, then 10 of the same |
| 3 | mini-HDMI → HDMI | adapter or 1.5m cable | ~$5 | |
| 4 | OLED display | 2.42" SSD1309, 128×64, **I2C version** | ~$14 | Many 2.42" modules ship SPI-configured; buy ones jumpered for I2C, or plan to move a resistor jumper |
| 5 | Matrix keypad | 3×4, membrane or button type | ~$5 | 7-wire ribbon, plugs straight to GPIO |
| 6 | Rotary encoder | EC11 with push switch, on breakout | ~$3 | KY-040 module is fine |
| 7 | D-pad | 5× 12 mm tactile switches in a cross + centre | ~$4 | **Digital, not analog** — the Pi has no ADC, so a thumbstick would need an MCP3008. Discrete 12 mm switches laid out as a cross beat a miniature 5-way nav switch: same familiar geometry, but sized for older hands |
| 8 | UPS board | 2×18650, 5 V out, power-path charging, I2C fuel gauge | ~$22 | Must confirm: charges while running, exposes battery % over I2C, GPIO passthrough |
| 9 | 18650 cells | 2× quality 3400–3500 mAh (Samsung 35E / LG MJ1 class) | ~$10 | Reputable seller only — fake-capacity cells are rampant |
| 10 | microSD card | 32 GB, A1 class, name brand | ~$8 | OS + app + 2.1 GB library |
| 11 | Wall adapter | Per UPS board spec | ~$8 | The UPS board dictates this, not the Pi |
| 12 | Enclosure + misc | box, wires, perfboard, screws | ~$20 | |

Per-unit total ≈ **$120**. For the 10-unit batch, buy parts in bulk (AliExpress-class pricing drops most line items 20–40%) — but **only after one complete unit is validated end-to-end**.

## GPIO pin map (BCM numbering)

Assumes the I2C display. I2C bus is shared by the OLED and the UPS fuel gauge (different addresses — typically 0x3C and 0x36).

| Function | BCM pins |
|---|---|
| I2C (OLED + fuel gauge) | 2 (SDA), 3 (SCL) |
| Keypad rows | 5, 6, 13, 19 |
| Keypad columns | 12, 16, 20 |
| Encoder A / B / push | 17, 27, 22 |
| D-pad centre (Play/Pause) | 23 |
| D-pad ◀ / ▶ | 25, 26 |
| D-pad ▲ / ▼ | 7, 8 |
| Reserved (debug UART) | 14, 15 — keep free |
| Spare | 4, 9, 10, 11, 18, 21, 24 |

**17 pins used, 7 spare.** The 3×4 keypad and the D-pad freed up four lines versus the original 4×4-plus-seven-buttons plan, which leaves room if the display ends up SPI-only (10 MOSI, 11 SCLK, 8 CE0, plus two for DC/RST) — in that case ▲▼ move to 4 and 18.

All buttons and keypad use internal pull-ups, switch to ground — no external resistors needed.

## Prototyping hardware: Pi 400 (on hand)

A Pi 400 is available now and is a fine development stand-in — full 40-pin GPIO on the rear header, same Bluetooth/HDMI stack, same OS image as the Zero 2 W (Raspberry Pi OS images boot on both). Phases 0–2 run on it as-is, and its built-in keyboard means Phase 0 runs on real Pi hardware.

Notes: the Pi 400 is much faster than the production Zero 2 W, so **performance must be re-validated on the real Zero 2 W** before the batch buy; jack audio uses the same USB DAC as production; the battery phase needs the Zero 2 W + UPS board.

## Phases

### Phase 0 — Software on a laptop (no hardware needed, start today)

The app is a state machine around libmpv; none of it needs a Pi. Run it on the dev machine with keyboard keys standing in for every physical control, and a terminal line (or pygame window) standing in for the OLED.

- Project scaffold, hymn index (number → title → file), config/settings store
- Selection flow: digit entry, T9 title search, browse list
- Playback via libmpv: play/pause/stop, seek, pitch-preserved speed (`scaletempo2`), volume
- Hardware abstraction layer: `Input` and `Display` interfaces with `KeyboardInput`/`TerminalDisplay` implementations now, GPIO/OLED implementations in Phase 1

**Exit criteria**: full hymn-selection-and-playback session driven from the keyboard, using a handful of sample MP4s.
**Testing**: Tier 1 of [TESTING.md](TESTING.md) — the whole suite runs on a laptop in a tenth of a second.
**Effort**: the bulk is Claude-driven; expect ~1 weekend of your time reviewing and steering.

### Phase 1 — Bench prototype (weekends 1–2 after parts arrive)

Pi (400 for comfort, or the prototype Zero 2 W) + OLED + keypad + encoder + buttons on dupont wires/perfboard. No battery, no case.

1. Flash Raspberry Pi OS Lite (64-bit), enable I2C, copy sample hymns
2. Wire **one peripheral at a time**, each verified before moving on: `pytest -m device` names the pin that is not wired (Tier 2 of [TESTING.md](TESTING.md)). OLED → keypad → encoder → D-pad
3. Swap the Phase 0 keyboard/terminal implementations for GPIO/OLED ones
4. Audio out through the headphone jack

**Exit criteria**: type `347` on the keypad, see the title on the OLED, hear it on the jack; pause, seek, and speed all work from the physical buttons. *The device is demonstrably real at this point.*
**Effort**: ~2 weekends (soldering + integration debugging).

### Phase 2 — Outputs: Bluetooth + HDMI (weekend 3)

> Bluetooth is designed in detail in **[BLUETOOTH.md](BLUETOOTH.md)** — architecture, screen flows, audio routing, and the build order that keeps protocol debugging away from UI debugging.

- ✅ Bluetooth menu on OLED: scan / pair / connect / disconnect / forget (BlueZ over D-Bus); auto-reconnect to last-used speaker when BT is the selected output; per-output volume memory — *built and exercised against the fake backend; the real BlueZ backend is written but untested on hardware*
- Explicit output selection menu (Jack / BT / HDMI), persisted
- HDMI: mpv full-screen via DRM/KMS, static `screensaver.png` when idle/stopped, freeze-frame on pause, quiet boot (no console text, no rainbow splash)

**Exit criteria**: pair a speaker using only the OLED and controls; play a hymn to a TV with nothing but splash image and video ever visible.
**Effort**: 1 weekend, *but Bluetooth is the flakiest part of the whole project* — pairing/reconnect edge cases may spill into evenings. Budget patience.

### Phase 3 — Battery (1 weekend)

- Mount Pi on UPS board, install cells
- Read fuel gauge over I2C → battery % + charging state on OLED status line
- 15% low-battery warning; safe automatic shutdown at ~5%
- **Validation**: one real 8-hour continuous-playback run on battery, and one full charge-while-playing session

**Exit criteria**: the 8-hour run completes; pulling the wall adapter mid-hymn is a non-event.

### Phase 4 — Hardening + enclosure (1–3 weeks, elastic)

- Read-only root filesystem (overlay mode); small writable settings partition with atomic writes
- systemd service: app starts on boot, restarts on crash; boot-to-ready ≤ 15 s
- Load the full 517-hymn library, build the final index
- Yank test: cut power 20× at random moments, device must always boot clean
- Enclosure: project box + drill is fine for v1 (3D print if available); panel cutouts for OLED, keypad, encoder, buttons, charge port, headphone jack, HDMI

**Exit criteria**: a volunteer who has never seen the project can be handed the box and play a requested hymn with no instructions beyond one laminated card.

### Phase 5 — Production run (10 units)

The immutable-SD-card design makes replication nearly free on the software side:

1. **Golden image**: once unit #1 passes Phase 4, its SD card *is* the product. `dd` it to an image file; flashing 10 cards is an afternoon. Per-device settings (paired speakers, volumes) live on the writable partition and start factory-fresh on each clone.
2. **Validate one, then buy nine**: the single prototype Zero 2 W must pass real-service testing (video via HDMI, Bluetooth to the church's speaker, USB-DAC audio, full 8h battery run) before the batch order.
3. **Repeatable wiring**: for 10 units, replace free-hand point-to-point wiring with a small soldered protoboard "hat" (or a cheap custom PCB from JLCPCB-class fabs, ~$2/board) that the keypad ribbon, encoder, buttons, and OLED plug into. One evening of layout saves ten evenings of debugging mis-wired units.
4. **Enclosure at quantity**: 3D printing wins at 10 units — print time is cheap, drilling identical boxes by hand ten times is not.
5. **Assembly estimate**: after unit #1, expect ~2–3 hours per unit (solder hat, mount, flash, smoke-test).
6. **Batch acceptance test**: the per-unit checklist in [TESTING.md](TESTING.md) — `pytest -m device`, hymn 001 to all three outputs, a power yank, a sane battery gauge, and a reboot that reconnects to the church's own speaker.

## Known risk areas (in order)

1. **Bluetooth audio (Phase 2)** — BlueZ pairing/reconnect quirks. Mitigation: test with the church's actual speaker early; keep the jack as the always-works fallback.
2. **Clean HDMI boot (Phase 2)** — hiding every trace of Linux takes a few config iterations (`disable_splash`, quiet cmdline, custom splash service).
3. **UPS board choice (Phase 3)** — boards vary in quality and I2C support. Confirm fuel-gauge readability and charge-while-running before buying; read recent reviews.
4. **Enclosure (Phase 4)** — always takes longer than the electronics. Keep v1 ugly and functional.

## Open questions carried from SPEC.md

1. Source file naming → resolved during Phase 4 library load (rename/manifest script).
2. Factory-default output → decide in Phase 2; jack is the provisional default.
3. Enclosure design → Phase 4.
4. Charger spec → dictated by whichever UPS board is bought (Phase 3 purchase, but order with the initial batch to save shipping).
