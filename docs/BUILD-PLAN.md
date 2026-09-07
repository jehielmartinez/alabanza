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
| 5 | **Control PCB** | Custom 2-layer board — keypad, D-pad, encoder, OLED, Pi socket | ~$15 | Board + all switches, diodes, encoder, passives, connectors. Full BOM in [HARDWARE.md](HARDWARE.md). Replaces the separate keypad / encoder breakout / D-pad line items |
| 6 | Power module | PB0063A LiPo charger/boost | TBD | Prototype choice; record its specs on arrival — see [HARDWARE.md](HARDWARE.md) |
| 7 | LiPo battery | Capacity sets prototype runtime | TBD | The 8 h target is a product-stage goal; the prototype only has to run long enough to test |
| 8 | microSD card | 32 GB, A1 class, name brand | ~$8 | OS + app + 2.1 GB library |
| 9 | Wall adapter | Per the PB0063A's input spec | ~$8 | |
| 10 | Enclosure + misc | box, screws, standoffs, panel hardware | ~$20 | No perfboard or hookup wire — the control PCB replaced both |

Per-unit total ≈ **$120**. For the 10-unit batch, buy parts in bulk (AliExpress-class pricing drops most line items 20–40%) — but **only after one complete unit is validated end-to-end**.

## GPIO pin map (BCM numbering)

Assumes the I2C display. The prototype's only I2C device is the OLED (0x3C); **0x36 stays reserved** for the fuel gauge that returns at product stage ([SPEC.md](SPEC.md) decision 21), so nothing else may claim it.

This map is the source of truth; [HARDWARE.md](HARDWARE.md) translates it to physical header pins.

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

All buttons and keypad use internal pull-ups, switch to ground — no external resistors needed. The one exception is the rotary encoder, whose A/B lines get an RC filter on the control PCB; see [HARDWARE.md](HARDWARE.md).

## Prototyping hardware: Pi 4 Model B (on hand)

A Pi 4 Model B is the development stand-in. Phases 0–2 run on it as-is.

It is the right stand-in because it is a **BCM2711**, one generation from the
Zero 2 W's BCM2710 and on the same side of every line that matters here:

| | Pi 4 B (bench) | Zero 2 W (production) |
|---|---|---|
| H.264 decode | hardware, V4L2 M2M `/dev/video10` | hardware, same interface |
| GPIO | `/dev/gpiochip0`, classic BCM block | same |
| KMS overlay | `vc4-kms-v3d` | same |
| OS image | one 64-bit Raspberry Pi OS image boots both | |

So the mpv `--hwdec` flags, the `config.txt` quiet-boot work and the whole GPIO
layer are written once and carry over. Jack audio uses the same USB DAC as
production.

**A Pi 500 is also on hand and is deliberately not used for this.** It is a Pi
5–class BCM2712, which *dropped the hardware H.264 decoder* — it plays the 480p
library in software — and moves GPIO behind the RP1 southbridge, where
`RPi.GPIO` and `pigpio` do not work at all and `gpiozero` needs ≥2.0.1.post3 for
the `gpiochip4`→`gpiochip0` renumbering. Both differences point away from the
Zero 2 W, so decode config and GPIO behaviour tuned there would be thrown away.
It stays useful as the fast machine for editing and running the Tier 1 suite.

Two cautions that survive the switch:

- The Pi 4 B is still **much faster and has 2–16× the RAM** of the production
  Zero 2 W, so boot-to-ready, mpv startup latency under 512 MB and thermals
  **must be re-validated on the real Zero 2 W** before the batch buy.
- The Pi 4 B **has a 3.5 mm analog jack and the Zero 2 W does not.** Do not let
  audio quietly come out of it; production audio is the USB DAC, and
  `pytest -m device` checks for the DAC specifically. The micro-USB OTG adapter
  that DAC needs on the Zero exists only on the Zero.

The battery phase needs the Zero 2 W + power block regardless.

## Phases

### Phase 0 — Software on a laptop (no hardware needed, start today)

The app is a state machine around libmpv; none of it needs a Pi. Run it on the dev machine with keyboard keys standing in for every physical control, and a terminal line (or pygame window) standing in for the OLED.

- Project scaffold, hymn index (number → title → file), config/settings store
- Selection flow: digit entry, T9 title search, browse list
- Playback via libmpv: play/pause/stop, seek, pitch-preserved speed (`scaletempo2`), volume
- Hardware abstraction layer: `Input` and `Display` interfaces with `KeyboardInput`/`TerminalDisplay` implementations now, GPIO/OLED implementations in Phase 1 — *both now written (`input_gpio.py`, `oled.py`), untested on hardware*

**Exit criteria**: full hymn-selection-and-playback session driven from the keyboard, using a handful of sample MP4s.
**Testing**: Tier 1 of [TESTING.md](TESTING.md) — the whole suite runs on a laptop in a tenth of a second.
**Effort**: the bulk is Claude-driven; expect ~1 weekend of your time reviewing and steering.

### Phase 1 — Bench prototype (weekends 1–2 after parts arrive)

Pi (400 for comfort, or the prototype Zero 2 W) + OLED + keypad + encoder + buttons on dupont wires/perfboard. No battery, no case.

1. Flash Raspberry Pi OS Lite (64-bit), enable I2C, copy sample hymns
2. Wire **one peripheral at a time**, each verified before moving on: `pytest -m device` names the pin that is not wired (Tier 2 of [TESTING.md](TESTING.md)). OLED → keypad → encoder → D-pad
3. Run with the real controls and panel: `alabanza --gpio --oled-device`.
   Both flags *add* to the keyboard and terminal rather than replacing them, so
   an SSH session shows what the OLED shows and still has `q` to quit — which is
   what makes "the encoder does nothing" separable from "the app does nothing"
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

- Wire the PB0063A to the control PCB (5 V + GND) and connect the LiPo
- *(Deferred to product stage — no gauge on the prototype: battery %, the 15% warning and the 5% shutdown all come back with the integrated power block. See [SPEC.md](SPEC.md) decision 21.)*
- **Validation**: a continuous-playback run on battery (the 8-hour target is product-stage; the prototype measures what it actually achieves), and one charge-while-playing session

**Exit criteria**: the device runs untethered for a measured, recorded duration; pulling the wall adapter mid-hymn is a non-event.

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
3. **Custom control PCB**: a single board that *is* the front panel — keypad, D-pad, encoder and OLED on the front, Pi socketed on the back. Designed in KiCad, ~$2/board from a JLCPCB-class fab. Per-unit assembly becomes "press the Pi on, screw the board down" instead of ~22 hand-run panel wires. Design, rationale and pre-fab checklist: **[HARDWARE.md](HARDWARE.md)**.
4. **Enclosure at quantity**: 3D printing wins at 10 units — print time is cheap, drilling identical boxes by hand ten times is not.
5. **Assembly estimate**: after unit #1, expect ~2–3 hours per unit (solder hat, mount, flash, smoke-test).
6. **Batch acceptance test**: the per-unit checklist in [TESTING.md](TESTING.md) — `pytest -m device`, hymn 001 to all three outputs, a power yank, a sane battery gauge, and a reboot that reconnects to the church's own speaker.

## Known risk areas (in order)

1. **Bluetooth audio (Phase 2)** — BlueZ pairing/reconnect quirks. Mitigation: test with the church's actual speaker early; keep the jack as the always-works fallback.
2. **Clean HDMI boot (Phase 2)** — hiding every trace of Linux takes a few config iterations (`disable_splash`, quiet cmdline, custom splash service).
3. **Power module behaviour (Phase 3)** — no single board on the market meets all six power requirements, which is why the prototype uses a PB0063A and defers gauging entirely ([HARDWARE.md](HARDWARE.md)). The residual risks are behavioural, not electrical: does the module auto-start on load without a button press, and does it run while charging? Both are cheap to test, and both must be answered before a product board is designed around it.
4. **PCB respin (Phase 5)** — a mis-mirrored Pi socket or a switch placed under the wrong key legend is invisible until the boards arrive. Work the pre-fab checklist in [HARDWARE.md](HARDWARE.md); it is an hour against a two-week fab turnaround.
5. **Enclosure (Phase 4)** — always takes longer than the electronics. Keep v1 ugly and functional.

## Open questions carried from SPEC.md

1. Source file naming → resolved during Phase 4 library load (rename/manifest script).
2. Factory-default output → decide in Phase 2; jack is the provisional default.
3. Enclosure design → Phase 4.
4. Charger spec → dictated by the PB0063A's input; record it when the part arrives.
