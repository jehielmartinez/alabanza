# Alabanza — Bluetooth Design

> **Status: BUILT (except the real BlueZ backend, which is untested on hardware)**
> — Phase 2 of [BUILD-PLAN.md](BUILD-PLAN.md), implementing the Bluetooth and
> audio-routing decisions of [SPEC.md](SPEC.md) (decisions 5, 6, 9). Every flow
> below runs today against the fake backend: `uv run alabanza --oled`.
> One open question remains, marked **[?]**.

Bluetooth is the flakiest part of the project and the only subsystem where a
failure is *visible during a service*. Everything below is designed around one
rule: **the device never freezes, never lies about its state, and never plays
into a speaker that isn't there.**

## What Bluetooth has to do

From the spec:

| Requirement | Source |
|---|---|
| Scan / Pair / Connect / Disconnect / Forget, entirely from OLED + controls | Spec §Bluetooth |
| All paired speakers remembered across reboots | Spec §Bluetooth |
| Auto-reconnect at boot to the last-used speaker — **only** when BT is the selected output | Decision 9 |
| Failed reconnect → `BT: no conectado`; Play warns instead of playing into the void | Spec §Bluetooth |
| Output is an explicit menu choice, never auto-switched | Decision 5 |
| Selected output disappears → **pause + warn**, no silent fallback | Decision 5 |
| Volume remembered per output | Decision 6 |
| Settings survive a power yank (rare, atomic writes) | Decision 10 |

## Architecture

Three layers, mirroring how `Player` is already split from `App`:

```
  App (app.py)          policy: when to scan, when to retry, what to say
      │  polls a snapshot every tick (50 ms), issues fire-and-forget commands
      ▼
  BluetoothManager      mechanism: one interface, three implementations
      │
      ├── BluezBackend   real device — BlueZ over D-Bus, own worker thread
      ├── FakeBackend    dev machine — scripted devices, latencies, failures
      └── NullBackend    no adapter present — everything reports unavailable
```

### The non-negotiable: nothing blocks the tick loop

The app runs a 50 ms loop that reads input, ticks the state machine, and
redraws two displays. A BlueZ `Connect()` call takes 2–10 seconds and can hang
for 30. **No Bluetooth call may ever happen on that thread.**

So the backend owns a thread and the app never waits:

- **Commands are fire-and-forget.** `bt.connect(mac)` returns immediately.
- **State is a snapshot.** `bt.state()` returns an immutable dataclass, cheap,
  never blocks. The app diffs it against last tick to detect transitions.
- **Results arrive as data**, not callbacks — a `last_result` field with a
  monotonic `seq`. The app turns a new seq into an OLED flash message.

This keeps `app.py` what it is today: pure, synchronous, testable logic with no
threading in sight.

```python
@dataclass(frozen=True)
class BtDevice:
    mac: str
    name: str
    paired: bool
    connected: bool
    audio: bool          # advertises A2DP Sink — non-audio devices are hidden
    rssi: int | None = None

@dataclass(frozen=True)
class BtResult:
    seq: int             # increments per completed op; app flashes on change
    op: str              # pair | connect | disconnect | forget
    mac: str
    ok: bool
    error: str = ""      # short Spanish string, already screen-sized

@dataclass(frozen=True)
class BtState:
    available: bool = False        # adapter present and powered
    scanning: bool = False
    devices: tuple[BtDevice, ...] = ()
    busy_op: str = ""              # "" when idle
    busy_mac: str = ""
    busy_since: float = 0.0        # monotonic, for the elapsed counter
    last_result: BtResult | None = None
```

Commands: `scan(on)`, `pair(mac)`, `connect(mac)`, `disconnect(mac)`,
`forget(mac)`, `cancel()`, `close()`.

### D-Bus library — **decided: `dbus-fast`**

**`dbus-fast`** — pure Python, no system packages, actively
maintained (it's what Home Assistant's Bluetooth stack runs on), and it exposes
the `InterfacesAdded` / `PropertiesChanged` signals that discovery and
connection-loss detection need. The backend runs an asyncio loop inside its
worker thread and translates between the two worlds at the snapshot boundary.

Rejected: `bluetoothctl` + pexpect (screen-scraping an interactive CLI is how
this subsystem earns its reputation), `dbus-python` (needs a GLib mainloop and
system packages), `pydbus` (unmaintained).

### The BlueZ pairing agent

BlueZ refuses to pair without a registered agent. Speakers are Just Works
devices — they never ask for a PIN — so the backend registers a
`NoInputNoOutput` agent that auto-confirms and claims default-agent. **The
device has a keypad but will never prompt for a pairing code**; if a speaker
demands one, pairing fails with `Fallo al emparejar` rather than hanging.

## Audio routing: how "output = Bluetooth" actually reaches the speaker

Connecting a speaker in BlueZ does not move audio to it. Something has to route
mpv's output. Pi OS Lite ships no sound server at all.

**Recommendation: PipeWire + WirePlumber + `libspa-0.2-bluetooth`** on the Lite
image, with mpv's `ao=pipewire`, and output selection implemented as setting
mpv's `audio-device` property live.

| Salida | mpv `audio-device` | Resolved by |
|---|---|---|
| Jack | `pipewire/alsa_output.usb-*.analog-stereo` | first sink whose name contains `usb` |
| Bluetooth | `pipewire/bluez_output.<MAC>.a2dp-sink` | sink name contains `bluez_output` |
| HDMI | `pipewire/alsa_output.platform-*.hdmi-*` | sink name contains `hdmi` |

A new `audio.py` owns that resolution (rules + `auto` fallback), so per-unit
name variation never reaches the state machine. `Player` gains an
`audio_device` setter; switching output while playing costs a sub-second AO
reinit, which is acceptable and only happens on an explicit menu action.

Alternative considered: **bluez-alsa** (no sound server, mpv talks
`alsa/bluealsa:DEV=...`). Lighter and boots faster, but it's a niche daemon with
thinner maintenance, and PipeWire also gives us clean HDMI/USB sink switching
for free. Worth revisiting only if PipeWire costs too much on the Zero 2 W —
**measure on real hardware before committing.**

**Volume stays software (mpv).** A2DP absolute volume via AVRCP would fight the
per-output memory in `settings.py` and double-attenuate. The BT sink is pinned
to 100% once at connect; mpv's `volume` remains the single control.

## Screen flows

All BT screens use the existing list ViewModel: status bar + list rows + hint
row. No new event kinds are needed — the existing encoder / `#` / `*` / Menu
vocabulary covers everything.

**Three rows, not four.** The OLED fits four 12 px list rows, but these screens
always show a hint row and it is drawn over the fourth — so the list windows to
three and scrolls. Rendering the real pixels is what caught this: the forget
confirmation originally put its cursor on row four, where it was invisible.

### Entry

```
MENU                          BT_LIST                      BT_DEVICE
┌───────────────────────┐     ┌───────────────────────┐    ┌───────────────────────┐
│ MENU                  │     │ Bluetooth   buscando… │    │ JBL Flip 5          ✓ │
│───────────────────────│  #  │───────────────────────│ #  │───────────────────────│
│   Salida: Bluetooth   │ ──▶ │ > ✓JBL Flip 5         │──▶ │ > Desconectar         │
│ > Bluetooth           │     │   ·Bocina Iglesia     │    │   Olvidar             │
│   Reescanear bibliot. │ ◀── │    Buscar de nuevo    │ ◀──│   Volver              │
│   Salir               │ m/* │ gira y pulsa          │ m/*│ gira y pulsa          │
└───────────────────────┘     └───────────────────────┘    └───────────────────────┘
```

Glyph in column 1: `✓` connected · `·` paired, not connected · blank
discovered, not paired. (Both glyphs were checked against the vendored Terminus
font — `▸`, which an earlier draft of this document used, renders as a tofu box
and is not usable on this panel.) Paired devices sort first, then discovered by
signal strength. **Non-audio devices are filtered out** — a volunteer scanning
in a full church must not page through thirty phones and laptops.

### Controls on the BT screens: the encoder, and nothing else

Every Bluetooth screen is **turn and push**. No screen names a key it needs,
because the fewer controls the operator has to learn, the better — and that
counts keys advertised in a hint row, not just buttons on the panel. (The
device has no Menu, Stop or Speed buttons at all; see the control table in
[SPEC.md](SPEC.md).)

| Control | On BT_LIST | On BT_DEVICE |
|---|---|---|
| Wheel, or D-pad ▲▼ | scroll (3-row window, wraps) | scroll |
| Push, or `#` | paired → open BT_DEVICE · unpaired → **pair + connect** · last row → search again | run the action |
| `*` | back to MENU (stops scan) | back to BT_LIST |
| D-pad centre / ◀ ▶ | **still play and seek** — the BT screen never hijacks the transport | same |

Scanning has **no key of its own**. It starts by itself on entering the screen
whenever nothing is connected and nothing is playing — an operator who opens
this screen came here to fix exactly that — and it stops after 30 s, on leaving,
or before any connect. Re-scanning is the last row of the list, `Buscar de
nuevo`, reached by turning the encoder like everything else.

`#` and the D-pad's ▲▼ work as well as push and the wheel, as they do
everywhere in the app — they are simply never advertised. One action, one
advertised way to do it.

Pairing an unpaired device is one press, not two: "use this speaker" is a
single intent, so `pair` chains straight into `connect` and reports one result.

### Busy overlay

Any in-flight op replaces the list body — same mode, no new state:

```
┌───────────────────────┐
│ Bluetooth             │
│───────────────────────│
│  Conectando…      4s  │
│  JBL Flip 5           │
│                       │
│ *: cancelar           │
└───────────────────────┘
```

- **Leaving is allowed.** `*` returns to the previous screen; the operation
  keeps running and its result arrives as a flash message. Nothing is modal.
- **Timeouts**: pair 30 s, connect 15 s, disconnect 5 s, then fail with a
  message. The app enforces these itself — it does not trust the backend to
  return.

### Confirm before forgetting

`Olvidar` is the one destructive action, so it gets a confirmation: the question
goes in the status bar (`¿Olvidar?`) and the three rows below are the speaker's
name, `Sí`, and `No` — cursor defaulting to `No`. Turn and push, like the rest.

## Boot auto-reconnect

Runs **only** when `settings.output == "bluetooth"` and `last_bt_device` is set
(decision 9 — a device set to Jack must not spend its boot chasing a speaker).

```
boot ──▶ output == bluetooth and last_bt_device?
           │ no  ──▶ done, adapter left alone
           │ yes ──▶ connect(last)      status bar: BT rune + "…"
                       ├── ok    ──▶ normal idle screen
                       └── fail  ──▶ retry at +5 s, +15 s (3 attempts total)
                                       └── still failing ──▶ "BT: no conectado"
```

Retry policy lives in `app.py`, not the backend: the backend is mechanism, the
state machine is policy. After the third failure the device stops trying and
sits quietly — no reconnect loop chewing battery through a service.

**Pressing Play while BT is selected but not connected**: warn
(`BT: no conectado`) and do not start the hymn — *and* kick
one background reconnect attempt, so the second press a few seconds later
usually just works. This goes slightly beyond the spec's "warns instead of
playing", and is **decided: kept** — the operator's instinctive response to the
warning is to press Play again, and that second press should be the one that
works. The warning never claims the hymn is starting, so the retry can only
help.

## Losing the speaker mid-hymn

The backend's `PropertiesChanged` watch flips `connected` to false; the app
sees it on the next tick:

```
connected ──▶ disconnected  while output == bluetooth
    │
    ├── player active ──▶ PAUSE  + flash "BT perdido - pausado"
    └── idle          ──▶ status bar shows the struck-through BT rune
                          then: 3 reconnect attempts (0 s, 5 s, 15 s)
                                 └── recovered ──▶ "Reconectado - Play" — stays PAUSED
```

**Never auto-resume.** A hymn restarting by itself mid-service is worse than
silence; the operator presses Play — which is exactly why the recovery message
is `Reconectado - Play` and not a bare `BT reconectado`: a fast reconnect would
otherwise overwrite the only explanation of why the music stopped.

Retry sequences stay **silent until they give up**. Three identical
`Sin respuesta` flashes tell the operator nothing that the last one won't. Reconnecting to *the same* speaker is
recovery, not the silent fallback decision 5 forbids — that rule bars switching
to a *different* output, which this never does.

### Status bar, at a glance

`oled.py` already draws the BT rune when `output == "bluetooth"`. It gains two
states, both readable without staring:

| Situation | Status bar right side |
|---|---|
| Connected | BT rune + volume, as today |
| Connecting | BT rune + `…` |
| Not connected | BT rune **with a strike line through it** + `--` instead of a number |

No blinking — a flashing status bar in a dim sanctuary reads as a fault.

### Choosing Bluetooth as the output with nothing connected

Cycling `Salida` to Bluetooth while no speaker is connected **opens the
Bluetooth screen directly**. The operator's next question is always "which
speaker?", so the device asks it instead of waiting to be asked.

## Persistence

`settings.py` grows a remembered-name cache so the OLED can show real names
before the adapter answers:

```python
last_bt_device: str = ""                    # MAC — already present
bt_names: dict[str, str] = {}               # MAC -> friendly name, for offline display
```

BlueZ remains the source of truth for what is actually paired; `bt_names` is a
display convenience and is reconciled on every scan.

### ⚠ Read-only root filesystem interaction (Phase 4)

**BlueZ stores pairings in `/var/lib/bluetooth`.** Under decision 10's
read-only root, that directory must be bind-mounted onto the writable settings
partition, or **every pairing is lost on reboot** and auto-reconnect can never
work. This is easy to miss until unit #1 mysteriously forgets the church's
speaker, so it belongs in the Phase 4 checklist alongside the overlay setup.

## Scanning policy

Discovery floods the 2.4 GHz radio and audibly degrades A2DP.

- Scan only while BT_LIST is open, and auto-stop after **30 s**.
- Stop scanning before any pair/connect, and on leaving the screen.
- **Scanning is blocked during playback** (decided) — pressing `A` mid-hymn
  flashes `Detén la reproducción para buscar`. Connecting to an already-paired
  speaker stays available at all times, which is the only thing anyone needs
  mid-service. Pairing a *new* speaker is a before-the-service task, and a
  stuttering hymn is a worse failure than a deferred one.

## Error messages

Every BlueZ error becomes one short Spanish string sized for 128 px:

| BlueZ condition | OLED shows |
|---|---|
| `AuthenticationFailed`, `AuthenticationRejected` | `Fallo al emparejar` |
| `AuthenticationCanceled` | `Emparejado cancelado` |
| `br-connection-profile-unavailable` / no A2DP | `No acepta audio` |
| `Failed`, `ConnectionAttemptFailed` | `No se pudo conectar` |
| adapter off / missing | `Bluetooth apagado` |
| app-side timeout | `Sin respuesta` |
| `AlreadyExists` / `AlreadyConnected` | treated as success, no message |

## Developing this without a Pi

`FakeBackend` makes the whole flow runnable on the laptop, which matters because
BlueZ edge cases are exactly what breaks in the field. Its roster:

| Fake device | Behaviour | What it rehearses |
|---|---|---|
| JBL Flip 5 | pairs and connects normally; starts out paired | the happy path, and boot auto-reconnect |
| Bocina Iglesia | connects, then drops 20 s later — once | pause + warn + recovery mid-hymn |
| Soundcore 2 | pairing always fails | the error message path |
| Bocina Vieja | never answers a connect | the app-side timeout |
| iPhone de Ana | not an audio device | must never appear in the list |

It advances only when the app polls `state()` — no threads, so the same key
presses always produce the same run. Select it with `--bt fake|none|real`
(default `fake`), and watch the real pixels with `--oled`.

Bocina Iglesia is the important one: it is the only way to rehearse the
pause-and-warn path before a Sunday morning does it for us. Driving these five
through the state machine is what surfaced three defects that reading the code
did not — a stale snapshot swallowing the command right after a cancel, a
retry sequence flashing `Sin respuesta` three times, and a reconnect message
erasing the only explanation of why the music had stopped.

## Build order

| # | Module | Status |
|---|---|---|
| 1 | `bluetooth.py` — dataclasses, protocol, `NullBackend` *(no deps)* | ✅ done |
| 2 | `bt_fake.py` + `--bt` flag — the whole flow from the keyboard | ✅ done |
| 3 | `app.py` — `Mode.BT_LIST` / `Mode.BT_DEVICE`, snapshot polling, retry policy, pause-on-loss, Play-blocked warning | ✅ done |
| 4 | `oled.py` — struck-through rune, connecting state | ✅ done |
| 5 | `audio.py` + `Player.audio_device` — sink resolution, live switching | ✅ written; the PipeWire-vs-bluez-alsa question below only changes the matching rules |
| 6 | `bt_bluez.py` — the real backend, last, against a proven UI | ⚠ written, **never run against BlueZ** — first Pi session is its first test |

Steps 1–4 need no hardware and no BlueZ; only 5–6 do. Bluetooth's reputation
comes from debugging protocol and UI at the same time — this order refuses to.

What is *not* built: nothing shares `settings.json` schema migrations (the new
`bt_names` map simply defaults to empty on an old file), and the
`/var/lib/bluetooth` bind-mount is Phase 4 work, so pairings will not yet
survive a reboot on a read-only root.

**Exit criteria** (extends Phase 2's): pair the church's actual speaker using
only the OLED and controls; play a hymn to it; power the speaker off mid-hymn
and watch the device pause and say so; power it back on and reconnect from the
menu; reboot and have it reconnect by itself.

## Decisions

1. **D-Bus via `dbus-fast`**, in a worker thread running its own asyncio loop.
2. **Retry-on-Play kept**: a Play press while BT is selected but disconnected
   warns *and* fires one background reconnect attempt.
3. **Scanning blocked during playback**; connecting to paired speakers is
   always available.
4. **Snapshot polling, not callbacks** — `app.py` stays synchronous and pure.
5. **Fake backend first, real BlueZ last** — never debug protocol and UI at
   the same time.
6. **Never auto-resume** after a reconnect; the operator presses Play.
7. **The Bluetooth screens are encoder-only.** Scanning is automatic plus a list
   row rather than a key; hints teach the interaction (`gira y pulsa`) instead
   of enumerating keys. Fewer controls to learn is worth more than a shortcut.

## Open questions

1. **[?]** PipeWire vs. bluez-alsa on the Zero 2 W — decide by measuring CPU
   and boot time on real hardware. Blocks build step 5 only; steps 1–4 and 6
   are unaffected.

Closed: whether `BT: no conectado` should hint at switching the speaker on, in
case the church's own powers itself off when idle. It stays as it is — the
message says what is true, and the operator's next move is the Bluetooth screen
either way.
