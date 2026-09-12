# Alabanza — Testing Strategy

Companion to [SPEC.md](SPEC.md) and [BUILD-PLAN.md](BUILD-PLAN.md).

This device fails in front of a congregation, on hardware nobody can debug
mid-service, in ten identical copies. That shapes everything below:

1. **The failure paths matter more than the happy path.** A hymn that plays is
   the easy case. A speaker that dies at verse two is the one worth pinning.
2. **Almost nothing needs a Pi.** The logic is a pure state machine over a
   player, a Bluetooth backend and a clock. Only the last mile — GPIO, I2C,
   BlueZ, sinks — needs real hardware, and it gets its own tier.
3. **Ten units means the checks have to be repeatable by hand too**, so the
   manual tiers below are checklists, not vibes.

## The tiers

| Tier | What it proves | Where it runs | When |
|---|---|---|---|
| **1. Automated, off-device** | the logic, the screens, the failure paths | any laptop, ~0.1 s | every change |
| **2. Automated, on-device** | the hardware is wired and configured | the Pi, `-m device` | Phase 1 onward, and per unit |
| **2b. Interactive, on-device** | every control reports the right thing, and the panel shows it | the Pi, by hand | bringing up a board, and per unit |
| **3. Endurance & abuse** | it survives a real service and a power yank | the Pi, by hand | Phase 3–4 |
| **4. Batch acceptance** | *this* unit is fit to hand over | each of the 10, by hand | Phase 5 |
| **5. The volunteer test** | someone who has never seen it can use it | a real person | before shipping |

Tier 1 is the only one that runs unattended, so it carries the weight.

## Tier 1 — automated, off-device

```sh
cd app
uv run --extra test pytest              # everything; device tests deselect themselves
uv run --extra test pytest -k bluetooth # one area
UPDATE_GOLDEN=1 uv run --extra test pytest   # accept intended screen changes
```

| Module | Covers | Tests |
|---|---|---|
| `test_library.py` | filename and manifest parsing, T9 search, browsing | 16 |
| `test_settings.py` | atomic saves, corrupt files, per-output volume | 11 |
| `test_audio.py` | which sink each output resolves to | 8 |
| `test_controls.py` | the control set, and the four relocated functions | 35 |
| `test_bluetooth.py` | pairing, timeouts, losing a speaker mid-hymn | 32 |
| `test_screens.py` | golden pixels + layout invariants | 41 |
| `test_pins.py` | the pin map, and the documents that copy it | 10 |
| `test_hwtest.py` | the bring-up panel: coverage map, splash, bus failures | 16 |
| `test_player_video.py` | which video options mpv gets, and when video is off | 6 |
| `test_input_gpio.py` | the keypad scan thread's failure behaviour | 7 |

`test_input_gpio.py` imports the GPIO backend, so it needs `gpiozero` and
skips where the `device` extra is not installed. Nothing in it touches a pin.

### Three things make this tier possible

**An injected clock.** `App(..., clock=...)` and `FakeBackend(..., clock=...)`
share one clock, so a 30-second BlueZ timeout, a 3-attempt reconnect sequence
and a 30-second scan window all resolve instantly and exactly. Nothing sleeps;
the whole suite is 0.1 s. Tests wait on *state*, not durations —
`rig.advance_until(lambda r: r.player.paused)` rather than `advance(22)` — so
they do not turn flaky when a delay is retuned.

**Backends behind protocols.** `FakePlayer` stands in for libmpv, `FakeBackend`
for BlueZ. The fake Bluetooth roster is a cast of failures worth rehearsing:
a speaker that drops mid-hymn, one that refuses to pair, one that never
answers, and a phone that must never appear in the list.

**Screens rendered as text.** Golden files store the 128×64 frame as one
character per pixel, so a diff shows the change instead of "binary files
differ", and a failure prints the offending rows.

### Golden files vs. invariants

They catch different things, and the difference has been earned:

- **Goldens** catch *unintended* change. They will happily record a broken
  screen as the new truth, so they are necessary but not sufficient.
- **Invariants** catch *wrong*. `test_the_cursor_is_always_on_screen` walks
  every list screen position by position and asserts the cursor is on a row
  the hint row does not cover. That bug has now happened twice — the forget
  confirmation, and the menu when it grew a fifth entry — and a golden file
  would have blessed both.

Write the invariant whenever you can state the rule. Reach for a golden when
you can only say "it looked right".

### Conventions

- **Name the behaviour, not the method.** `test_it_pauses_rather_than_playing_into_nothing`,
  not `test_disconnect_handler`. These names are the spec of the appliance.
- **Drive through the real controls.** `rig.press(Kind.PUSH)`, not
  `app.mode = Mode.MENU`. A test that reaches past the input layer will not
  notice when a screen becomes unreachable.
- **Assert on what an operator sees** — the ViewModel and the flash message —
  rather than on private state, wherever the two agree.
- The `harness` fixture writes real settings to a temp file and constructs
  `App` from it, so startup behaviour (boot auto-reconnect) is exercised too.

## Tier 2 — automated, on-device

```sh
uv run --extra test --extra device pytest -m device
```

`tests/test_device.py` answers *is it wired and configured*, never *is the
logic right*. Everything is marked `device` and deselects itself anywhere that
is not a Raspberry Pi, so the laptop suite stays clean.

It checks: the I2C bus exists and the OLED answers at `0x3C`; a frame reaches
the panel; every GPIO pin in the [pin map](BUILD-PLAN.md) can be claimed;
PipeWire is running and the USB DAC resolves; the Bluetooth adapter is present
and powered; and `/var/lib/bluetooth` is writable — under a read-only root that
must be bind-mounted or **every pairing is lost on reboot**.

Run it after wiring each peripheral in Phase 1: the failure names the pin.

## Tier 2b — the controls and the panel, by hand

```sh
uv run alabanza-hwtest          # --no-oled if the panel is not populated yet
```

Tier 2 asks *is this pin claimable*, which is a question about wiring that a
machine can settle alone. It cannot ask whether **the key marked 7 reports a
7** — and a swapped row, a mirrored J1 and a mislabelled switch are the top
three items on [HARDWARE.md](HARDWARE.md)'s pre-fab checklist. That one needs
a finger and an eye, so it gets a tool instead of a test.

Press a control; the panel names it in 20 px with the BCM pins it arrived on,
and a coverage map along the bottom fills in as each of the 21 controls
responds. A board is signed off by sweeping it until the map is full. On exit
the terminal lists whatever never answered, with its pins:

```
19 control(s) never responded:
  Tecla 7        BCM13 BCM12
  Rueda +        BCM17 BCM27
```

It tests the panel at the same time, because everything it reports, it
reports on the OLED. The startup frame draws a border on the outermost pixels
and a line of accented Spanish: a clipped border is a wrong panel height or
start-line, missing accents mean the vendored font did not load. The run also
ends with a frame count and how many I2C writes failed — at the 400 kHz
`provision.sh` sets, that number is a real measurement of the bus, and the
difference between a panel worth soldering down and one worth re-checking.

Exits non-zero if any control never responded or the panel dropped a frame,
so it works as a gate. `--seconds N` bounds a run for scripting.

## Tier 3 — endurance and abuse (by hand, Phase 3–4)

Automation cannot answer these; a person and a stopwatch can.

| Check | Pass condition |
|---|---|
| 8-hour battery run | plays continuously from full to the 5% shutdown, unplugged *(product stage — the prototype has no gauge, so it runs to cutoff and the duration is simply recorded)* |
| Charge while playing | plays through a full charge cycle without a dropout |
| Power yank ×20 | cut power at random moments; boots clean every time |
| Boot to ready | ≤ 15 s, no console text and no rainbow splash on HDMI |
| A full service | one real Sunday, jack and Bluetooth, no intervention |
| Thermal | an hour of playback in a closed enclosure without throttling |

The yank test is the one people skip. It is also the one the read-only root
and atomic settings writes exist for, so it is the one that proves them.

## Tier 4 — batch acceptance (per unit, Phase 5)

Every unit passes this before it goes to a church. It is deliberately short
enough to actually get done ten times:

1. `pytest -m device` — all green
2. `alabanza-hwtest` — all 21 controls respond, no failed panel writes
3. Hymn `001` plays to the jack, to a Bluetooth speaker, and to HDMI
4. The OLED shows a sane battery percentage, and it falls under load *(product stage only — no gauge on prototype units)*
5. Power yanked mid-hymn, then boots clean
6. Pair the church's own speaker; reboot; it reconnects by itself
7. The laminated card matches what the device actually does

## Tier 5 — the volunteer test

Hand the box to someone who has never seen it, with one laminated card, and
ask for hymn 347. Watch without helping. Every hesitation is a bug — in the
labels, the card, or the flow — and it is the only tier that can find those.
This is the real exit criterion for Phase 4.

## What is deliberately not tested

- **`bt_bluez.py`** has no automated coverage and cannot have any off-device;
  it is the reason Tier 2 exists. Its *flows* are covered through `FakeBackend`.
- **`player.py`** wraps libmpv thinly, so its *behaviour* is left to mpv —
  but which options mpv is constructed with is ours, and that is covered
  (`test_player_video.py`), because getting it wrong froze the whole
  appliance once. Tier 2 also checks that property reads still return.
- **The curses UI** is a development convenience; the OLED is the product.
- **`tools/`** (downloader, provisioner) run once at provisioning with a human
  watching. The output they produce — the manifest — is covered in Tier 1.

## Bugs this suite has already caught

Kept as a record of what kind of testing pays here — every one is a defect
that reading the code did not reveal:

| Found by | Bug |
|---|---|
| driving the flows | a stale snapshot swallowed the command right after a cancel |
| driving the flows | a retry sequence flashed `Sin respuesta` three times |
| driving the flows | a reconnect message erased why the music had stopped |
| rendering pixels | the forget confirmation put its cursor on an invisible row |
| rendering pixels | the menu did the same once it grew a fifth entry |
| layout invariant | long hymn titles ran off the panel with no ellipsis |

Four of the six are in the Bluetooth and screen layers — which is exactly
where the spec says the risk is.

And two the suite did **not** catch, found the expensive way instead — an
evening on the bench, chasing what looked like a dead keypad:

| Found by | Bug |
|---|---|
| a frozen device | mpv with no display attached stopped answering `volume`, and the loop reads it every tick — keypad, keyboard and panel all froze together |
| a dead keypad | one exception ended the scan thread while the app ran on, with nothing on the panel to say so |

Both now have tests that reproduce them, which is the only useful response to
a bug that got out. The first is also the more instructive: neither failure
was where the symptom pointed, and the controls were never at fault.
