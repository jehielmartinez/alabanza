# Alabanza — Hardware / PCB Design

Companion to [SPEC.md](SPEC.md) and [BUILD-PLAN.md](BUILD-PLAN.md). This document
covers the custom PCB: what is on it, why each part is there, and what must be
verified before sending it to a fab.

Tool: KiCad. Fab target: JLCPCB-class, 2-layer, ~$2/board at qty 10.

## The board

**One board, and it is the front panel.** Everything mounts on it:

| Side | Contents |
|---|---|
| Front | 3×4 keypad, 5-key D-pad, rotary encoder, 2.42" OLED module |
| Back | Raspberry Pi Zero 2 WH (via 2×20 socket), power block, battery leads |

This supersedes the "small soldered protoboard hat" idea in
[BUILD-PLAN.md](BUILD-PLAN.md) Phase 5. The reasoning: every control has to
reach the panel anyway. A board that stacks on the Pi needs ~22 hand-run wires
per unit to get the controls out to the panel — precisely the free-hand wiring
the PCB exists to eliminate. Making the control board *be* the panel reduces
per-unit assembly to "press the Pi on, screw the board down."

Consequences that follow from the choice, and are not optional:

- The Pi is no longer stacked on anything, so **the 40-pin header is ours**. The
  Pi receives 5 V *from* our board through header pins 2/4.
- Nothing else can use the GPIO header — see [Power](#power-block) for what that
  did to the battery plan.
- Board size is driven by the front face (OLED window + key ergonomics), not by
  the Pi. The Zero's 65 × 30 mm is just a keep-out rectangle on the back.

## Schematic blocks

### 1. Keypad — 3×4 matrix, 12 keys

Twelve tactile switches on 4 rows × 3 columns, 7 GPIO instead of 12.

**Each key is an independent cell**, never chained to its neighbours:

```
COLn >────o  o────|<|────< ROWn
           SW      D
                (cathode toward the row)
```

**Diodes (1N4148W, SOD-123) are fitted on all 12 keys.** Without them, three
keys held in an L-shape produce a phantom fourth ("ghosting"). Nobody chords
three digits on a hymn player, so this is insurance rather than necessity — but
it costs about $0.60 across the whole board and cannot be added after fab.

The diodes also remove any risk from a mis-written matrix scan. Regardless,
firmware must scan by **driving one row low at a time with the other rows as
inputs (Hi-Z)**, never all rows as outputs — two driven rows shorted by a
keypress is a fault current straight through the GPIO pads.

### 2. D-pad — 5 keys, direct

No matrix, no diodes: each key owns a GPIO.

```
BTN_x >────o  o──── GND
```

Sharing the ground rail between the five is fine — unlike a scan net, there is
no path between two buttons through it.

### 3. Rotary encoder — EC11 with push switch

The EC11 is two independent devices in one body.

**Rotary contacts (A / C / B).** C is the common of both blades → GND. A and B
are switches to C, mechanically 90° out of phase; firmware reads *which changed
first* to get direction. Swapping A and B just reverses the knob — a one-line
software fix, not a respin.

**A and B each get an RC filter** — the only passives on the board that are not
optional:

```
        3V3
         │
        10k          (R1 for A, R2 for B)
         │
   A ────┼────> ENC_A
         │
       100nF         (C1 for A, C2 for B)
         │
        GND
```

τ = 1 ms, which swallows EC11 contact bounce while still settling far faster
than the ~25 ms between edges at a fast spin. **The 10 kΩ external pull-up is
what makes the cap safe**: the Pi's internal pull-up is ~50 kΩ, and 50 kΩ ×
100 nF is a 5 ms rise — slow enough to start eating edges when someone spins the
volume knob hard.

This matters because a bad bounce on a rotary reads as a *reverse* click, and
volume is the encoder's always-on job ([SPEC.md](SPEC.md) decision 6).

**Push switch (S1 / S2).** Electrically unrelated to rotation. Treated as a
sixth D-pad button: S2 → GND, S1 → `BTN_ENC`. No filter — a stray extra
menu-open is harmless where a stray reverse-volume-click is not.

Optional: tie the encoder's two panel mounting lugs to GND for a shield
connection.

### 4. No pull-ups or resistors on any switch

All keypad and button inputs use the Pi's **internal pull-ups, switch to
ground**, with software debounce (`gpiozero` `bounce_time`). The internal ~50 kΩ
is ample for on-board trace lengths. The encoder RC network above is the sole
exception.

### 5. Pi header — J1

Symbol `Connector:Raspberry_Pi_4`, footprint
`Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical`, **mounted on the
back side**.

The symbol is named Pi 4; the 40-pin pinout is identical across Pi 4 / Zero 2 W
/ Pi 400, so it is the correct symbol. Its Value/Description/Datasheet fields are
overridden to say Zero 2 W. *Clicking "Update Symbol from Library" will revert
those fields.*

Using this symbol rather than a generic 2×20 connector is deliberate: its pins
are labelled in **BCM numbering**, matching the pin map, which removes the
BCM→physical-pin translation step — the most likely way to produce a
correct-looking dead board.

Net assignments (BCM ↔ net, see [BUILD-PLAN.md](BUILD-PLAN.md) for the source
pin map):

| Net | BCM | Header pin |
|---|---|---|
| `ROW1` – `ROW4` | 5, 6, 13, 19 | 29, 31, 33, 35 |
| `COL1` – `COL3` | 12, 16, 20 | 32, 36, 38 |
| `ENC_A` / `ENC_B` | 17, 27 | 11, 13 |
| `BTN_ENC` | 22 | 15 |
| `BTN_OK` | 23 | 16 |
| `BTN_LEFT` / `BTN_RIGHT` | 25, 26 | 22, 37 |
| `BTN_UP` / `BTN_DOWN` | 7, 8 | 26, 24 |
| `SDA` / `SCL` | 2, 3 | 3, 5 |
| `+5V` (in, from power block) | — | 2, 4 |
| `+3.3V` (out, encoder pull-ups + OLED) | — | 1, 17 |
| `GND` | — | 6, 9, 14, 20, 25, 30, 34, 39 |

The KiCad symbol **stacks** the duplicated rails: wiring pin 1 wires 17, wiring
pin 6 wires all eight grounds, wiring pin 2 wires 4. Confirmed by ERC, which
reports none of the stacked partners as unconnected.

No-Connect flags belong on the genuinely unused pins: 8, 10 (GPIO14/15, debug
UART — deliberately reserved), 12, 40, 18, 7, 21, 19, 23 (spare GPIO), and
27, 28 (ID_SD/ID_SC HAT EEPROM).

### 6. OLED — 2.42" SSD1309, I2C

HiLetgo 2.42" SSD1309 128×64 module, purchased in the **4-pin I2C
configuration** (the 7-pin SPI variant is the same module jumpered differently).

| Signal | Goes to |
|---|---|
| GND | `GND` |
| VCC | **`+3.3V`** — not 5 V |
| SCL | `SCL` (GPIO3) |
| SDA | `SDA` (GPIO2) |

**Power it from 3.3 V.** The module accepts 3.3–5 V, and its onboard I2C
pull-ups tie to whatever VCC receives. At 5 V they would pull SDA/SCL to 5 V,
and **the Pi's GPIO is not 5 V tolerant** — a slow way to destroy GPIO2/3.

**Do not add I2C pull-ups.** The Pi has 1.8 kΩ fixed on GPIO2/3 and the module
carries its own; that is already two sets in parallel. A third would overload
the bus.

Add a 100 nF decoupling cap between +3.3V and GND at the module's pads.

Mounting: soldered to the front of the board via a 1×4 socket (removable — a
DOA display becomes a 10-second swap rather than desoldering a part with glass
bonded to it). **Mechanical load goes through the module's four M2 mounting
holes and standoffs, never through the 4 pins** — the glass is bonded to the
module PCB and will crack if the board flexes.

Bus addresses: OLED `0x3C`. The prototype has no other I2C device; `0x36` is
reserved for the fuel gauge that returns at product stage.

### 7. Power block

> **Off-board.** The board does not generate power; it receives 5 V on a 2-pin
> connector and passes it to J1 pins 2/4, and taps the fuel gauge onto the
> existing SDA/SCL.

#### Why the TP4056 was rejected

Three TP4056 Type-C modules with dual protection (DW01 + FS8205) were bought
before the gap was spotted. It is a **single-cell charger, not a UPS**, and it
misses three things [SPEC.md](SPEC.md) requires:

1. **No 5 V.** OUT+ is raw cell voltage, 2.5–4.2 V. The Pi needs 5 V.
2. **No load sharing.** Connect a load to OUT+ while charging and the TP4056
   cannot detect charge termination — it sees load current and never finishes,
   while the cell is charged and discharged at once. This breaks "device fully
   usable while plugged in and charging."
3. **No fuel gauge.** No I2C at all: no battery %, no 15% warning, no safe
   shutdown at 5%. The Pi has no ADC, so cell voltage cannot even be read.

Closing those gaps means a 5 V boost, an ideal-diode load-share circuit and a
separate MAX17048 — three pieces of analogue design, on a board whose digital
half is already validated, to replace a $25 part that arrives working.

**Decision: buy an integrated UPS module.** The TP4056s stay useful as bench
chargers for cells during development.

#### Requirements the replacement had to meet

Every line traces to a spec requirement.

| Requirement | Why |
|---|---|
| **5 V output, ≥2 A** | Zero 2 W peaks well above its ~2 W average; brownouts corrupt SD cards |
| **True power-path / load sharing** | "Usable while plugged in and charging" is a spec requirement, and the thing cheap boards silently lack |
| **Battery state over I2C** | Feeds OLED battery %, the 15% warning and the 5% shutdown |
| **≥20 Wh of cells** | 8 h at ~2 W. 2×18650 ≈ 25 Wh |
| **Not a HAT, no pogo pins** | The control PCB owns the 40-pin header; the Pi's underside is not accessible |
| **USB-C charge input** | Panel hardware consistency |

#### What was surveyed

Nothing on the market meets all six in one board. The Pi Zero power market splits
into ~1200 mAh handheld packs and large HATs for the Pi 4/5; the middle
("Zero 2 W + 25 Wh + I2C gauge, header free") is unserved.

| Option | 5 V out | Power path | I2C gauge | Cells | Verdict |
|---|---|---|---|---|---|
| Adafruit PowerBoost 1000C | 1 A ceiling | ✅ | ❌ (`LBO` pin only) | 1S | Underpowered; no percentage |
| Waveshare UPS HAT (C) | ~1.8 A | ✅ | ✅ INA219 | 1S | HAT form factor; **micro-USB** input |
| Waveshare UPS Module 3S | 5 A | ✅ | ✅ | 3S | Standalone, but 3 series cells |
| PiSugar S | 2.5 A | ✅ | ❌ (external-power detect only) | 1200 mAh | **~4.4 Wh ≈ 2 h.** Fails runtime outright; pogo pins |
| Pi-Ener-lite | 2.5 A | ✅ | ✅ CW2015 | 1× 18650 | ~12 Wh; pogo pins; single-vendor Tindie supply risk |

#### Decision: prototype now, integrate later

**Prototype (v1): a PB0063A LiPo charger/boost module and a LiPo battery. No
battery gauge.**

The gauge is deliberately out of scope for the first board. It is the only
remaining piece that needs a second module and a second I2C device, and it
answers a question ("how much is left?") that does not have to be answered to
prove the device works. Every other function — keypad, encoder, OLED, audio,
Bluetooth, HDMI — can be validated on the prototype without it.

If this becomes a product, the power block moves onto the main board and the
gauge comes back with it. See [Future: v2 integration](#future-v2-integration).

> **Specs to record when the PB0063A arrives** — this part could not be
> identified from public sources, so its datasheet numbers are not yet in this
> document. Fill in: continuous output current at 5 V, whether power-path /
> charge-while-running is supported, charge current, and input connector type.

Deferred with the gauge, and **not** available on the prototype:

- Battery percentage on the OLED status line
- The 15% low-battery warning
- Safe automatic shutdown at ~5%

The read-only root filesystem already makes an abrupt power loss a non-event
([SPEC.md](SPEC.md) decision 10), so the prototype simply runs until it stops.
This is a scope decision, not an oversight — see [SPEC.md](SPEC.md) decision 20.

#### If the gauge is wanted later without a board respin

A MAX17048 breakout wires onto the cell and the existing I2C bus with four
wires. Its address is fixed at the chip level at **0x36**, matching what
[BUILD-PLAN.md](BUILD-PLAN.md) already assumes, so adding it later changes no
pin assignment. Two notes if that happens:

- The MAX17048 is powered *by the cell* (VDD 3.0–4.2 V), not by 3.3 V. If the
  breakout's I2C pull-ups tie to the battery rail they will pull SDA/SCL toward
  4.2 V, which the Pi's GPIO will not tolerate. Trace them; lift them if so. The
  bus already has the Pi's 1.8 kΩ plus the OLED's.
- Its `ALERT` pin can drive a spare GPIO (BCM 4, 9, 10, 11, 18, 21, 24) for a
  low-SOC interrupt rather than polling.

#### Board-side interface

Regardless of which module is chosen, the control PCB needs:

- **2-pin connector** for 5 V + GND in, feeding J1 pins 2/4. Polarised
  (JST-XH), because reversing it destroys the Pi.
Nothing else. The gauge connector is omitted from the prototype — if it is
added later it wires to the same I2C nets with flying leads, no respin needed.

Feeding 5 V into the Pi's header pin bypasses the Pi's own input protection.
This is normal for a HAT-powered Pi, but means the upstream module owes it a
clean, current-limited 5 V.

#### Cell note

The prototype uses a single LiPo pack, so cell topology is not a live question.
It becomes one at product stage: if the chosen part is single-cell (1S), two
18650s go in **parallel** (1S2P — 3.7 V, ~6800 mAh, ~25 Wh), never in series.
Series wiring into a 1S charger destroys it. ClockworkPi's uConsole uses exactly
this 1S2P arrangement.

## PCB layout rules

1. **Pin-1 mirroring on J1.** The socket mounts on the back, so the footprint is
   flipped to the bottom layer and **the pad layout mirrors**. Verify physically:
   hold the Pi behind the board in its real orientation and confirm its pin 1
   (square pad, corner nearest the microSD slot) lands on the socket's pin 1.
   Getting this backwards mirrors every GPIO across the connector — the board
   looks perfect and nothing works.
2. **Key placement must match key identity.** `PB1` has to physically be the `1`
   key and `PB13` the one under the ▲ cap. Set every switch's **Value** field
   (`1`…`9`, `*`, `0`, `#`, `▲`, `▼`, `◀`, `▶`, `OK`) before opening the PCB
   editor; reference designators alone tell you nothing at placement time. This
   is how a fab'd board ends up sending `2` when key `5` is pressed.
3. **Pi keep-out on the back.** A 2×20 socket holds the Pi ~8.5 mm off the
   board, so trimmed through-hole leads (~1–2 mm) clear — but nothing tall goes
   in that 65 × 30 mm rectangle.
4. **Pi orientation is dictated by ports, not routing.** Mini-HDMI, USB (DAC),
   power, and the microSD slot are all on the Zero's edges. Place the Pi so that
   edge faces the enclosure edge to be cut. Rotating it 180° for prettier
   routing buries the SD slot.
5. **Isolate the power block.** 1.5 A switching at the boost is the noisiest
   thing on the board; it must not share a ground return with the encoder's RC
   filters.
6. **Tie every header GND pin into the ground pour**, not just the one that
   satisfies the netlist.
7. Board outline and the four M2.5 Zero mounting holes (58 × 23 mm) come after
   the front face is laid out from real ergonomics.

## Future: v2 integration

The modules chosen above are a deliberate v1 decision, not a permanent one. The
intent is to fold the power block onto the control PCB in a later revision,
removing two boards and their wiring.

**Do it in this order, and only after v1 works.** v1's job is to establish the
*behaviour* — real current draw under video + Bluetooth, thermal performance in a
closed enclosure, whether pass-through is seamless. v2 then replicates a
known-good target instead of guessing at one.

The two halves are not equally hard:

- **MAX17048 — easy, do this first.** A TDFN part with a handful of passives, no
  inductor, no switching node. Deletes a whole breakout and its four wires for
  roughly $2 in parts, and removes the pull-up question entirely because the
  pull-ups become ours.
- **IP5306 — harder.** It is a switcher: inductor selection, thermal budget, and
  a layout where switching-node placement genuinely matters. Reference layouts
  are published (the IC exists to make power banks a two-part BOM), but it is
  unforgiving of a careless ground plane — and it lands next to the encoder's RC
  filters, which is what layout rule 5 is already about.

**Read a shipping product's schematic first.** ClockworkPi's uConsole solves the
same problem — 2× 18650, USB-C, charge-while-running — with a single X-Powers
**AXP228** PMU; their newer PicoCalc uses the **AXP2101**, marketed as a
"Single Cell NVDC PMU with E-gauge". One such chip collapses charger, power path,
regulation *and* fuel gauge onto the I2C bus already routed here. Their
schematics are GPL v3 at
[github.com/clockworkpi/uConsole](https://github.com/clockworkpi/uConsole)
(`clockwork_Mainboard_V3.14_Schematic.pdf`).

This is also why no module vendor sells the all-in-one board: commercial
products use a PMU IC designed onto the mainboard, not a breakout. Caveat to
check in that schematic: the AXP family is built to feed a SoC with 3.3 V-class
rails, and the uConsole drives a Compute Module — confirm whether the PMU's boost
can supply the Zero 2 W's 5 V rail or whether a separate boost stage is needed.

Worth checking at planning time: whether the chosen parts are in JLCPCB's assembly
library. At 10 units, having the fab place the fine-pitch parts is realistic and
removes hand-soldering risk.

Not a candidate for integration: the OLED. Replacing the module with a bare
SSD1309 means an FPC connector, the charge-pump passives and the bonded glass
panel — a large step in difficulty for no meaningful gain.

## Verification checklist before fab

Cheap checks that each prevent a wasted board run and a wasted batch order.

- [ ] ERC clean **with warnings enabled** — missing footprints and unannotated
      symbols report as warnings, not errors, and are easy to miss.
- [ ] All diodes annotated (`D1`–`D12`) with Value `1N4148W`; encoder annotated.
- [ ] Every switch's Value field set to its printed key legend.
- [ ] **Encoder pin C, not B, is the one going to GND.** Adjacent pins, both
      wires exit left — swapping them is electrically legal and yields a dead
      knob. ERC cannot catch it. Click the GND wire and confirm the highlighted
      net includes pin C.
- [ ] **OLED module pin order read off the physical board's silkscreen.** Order
      varies between batches on these modules; GND/VCC swapped destroys the
      display instantly.
- [ ] OLED confirmed answering at `0x3C` on a breadboard before fab.
- [ ] Measured from the physical OLED module: 4-pin pitch (expected 2.54 mm),
      mounting-hole pattern, and glass-to-PCB height (sets standoff length and
      panel cutout).
- [ ] J1 pin 1 orientation checked against a physical Pi, per layout rule 1.
- [ ] Footprint is `PinSocket` (female), not `PinHeader` (male).

## Bill of materials — board only

Additions to the per-unit list in [BUILD-PLAN.md](BUILD-PLAN.md). Replaces line
items 5 (keypad), 6 (encoder breakout), 7 (D-pad), and 8 (UPS board).

| Qty | Part | Notes |
|---|---|---|
| 1 | Custom PCB, 2-layer | ~$2 at qty 10 |
| 17 | Tactile switch | 12 keypad + 5 D-pad; 12 mm caps on the D-pad for older hands |
| 12 | 1N4148W diode, SOD-123 | Matrix anti-ghosting |
| 1 | EC11 rotary encoder with push | Bare part, not a KY-040 breakout |
| 2 | 10 kΩ resistor, 0805 | Encoder A/B pull-ups |
| 3 | 100 nF capacitor, 0805 | 2× encoder filter, 1× OLED decoupling |
| 1 | 2×20 female socket, 2.54 mm | J1, back-mounted |
| 1 | 1×4 socket, 2.54 mm | OLED, front-mounted |
| 4 | M2 standoff + screw | OLED mechanical mount |
| 1 | 2-pin JST-XH | 5 V power in from the UPS module |
| 1 | PB0063A LiPo charger/boost module | Power; specs to be recorded on arrival |
| 1 | LiPo battery | Capacity sets prototype runtime |

A KY-040 breakout would work in place of the bare EC11 (it carries the 10 kΩ
pull-ups already — fit only the caps), but a bare EC11 mounts directly to the
panel and is cheaper at quantity.
