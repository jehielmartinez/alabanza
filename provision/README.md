# Provisioning

Two scripts, one job each. Together they take a **fresh Raspberry Pi OS Lite
install** to a bench device you can run hymns on.

| Script | Runs on | What |
|---|---|---|
| `sync.sh` | the dev machine | mirror this working copy onto the Pi |
| `provision.sh` | the Pi | configure the board, install everything, verify |

## From a blank SD card

1. **Flash** Raspberry Pi OS **Lite (64-bit)** with Raspberry Pi Imager — or
   **Lite (32-bit)** for the original Zero W, which is ARMv6 and cannot boot
   the 64-bit image (see [The original Zero W](#the-original-zero-w) below).
   Do not format the card in Disk Utility first — Imager writes its own
   partition table. In Imager's settings, set the hostname, create the user, and **enable
   SSH with your public key**; that is the whole reason no keyboard or monitor
   is needed below.

2. **Boot it, and confirm you can reach it:**

   ```sh
   ssh user@host true      # must succeed without a password
   ```

3. **Push the repo and provision:**

   ```sh
   provision/sync.sh user@host
   ssh -t user@host '~/alabanza/provision/provision.sh'
   ```

   `provision.sh` asks for the sudo password once, up front. It takes a few
   minutes on the first run, most of it `apt` and compiling `lgpio`.

4. **Reboot if it asks.** Enabling I2C needs one, and so does a group change.

5. **Check it:**

   ```sh
   cd ~/alabanza/app
   uv run --extra test pytest                              # Tier 1
   uv run --extra test --extra device pytest -m device     # Tier 2
   uv run alabanza-hwtest                                  # Tier 2b, by hand
   ```

   Tier 2 proves each pin can be claimed. `alabanza-hwtest` is the one that
   proves the key marked 7 reports a 7 — press every control and watch the
   coverage map on the OLED fill in. Run it on any board you have just
   built; [TESTING.md](../docs/TESTING.md) explains what it catches that
   Tier 2 cannot.

## Then, every time you change something

```sh
provision/sync.sh user@host
```

A couple of seconds. `provision.sh` only needs re-running when a dependency or
a board setting changes — and it is idempotent, so running it anyway is free.

## The library

`sync.sh` **excludes** the 2.3 GB hymn library by default, because pushing it
on every edit would make the loop unusable. Once, at the start:

```sh
provision/sync.sh user@host --library
```

For bench work you do not need all 517 — a handful of MP4s plus a
`manifest.json` in `tools/library/` is enough to exercise every code path.

## Why the scripts do what they do

Three of the steps are not obvious, and each one cost an evening to find:

- **SPI is explicitly disabled.** BCM 7 and 8 are CE1/CE0. With SPI enabled the
  kernel owns those lines, `lgpio` cannot claim them, and the D-pad's ▲▼ are
  dead while the other three keys work perfectly. That asymmetry reads as a
  wiring fault and is not one.

- **`swig`, `python3-dev`, `build-essential` and `liblgpio-dev` are installed.**
  The PyPI `lgpio` package is a C extension and needs all four. `liblgpio-dev`
  is the one that hides: Pi OS preinstalls `liblgpio1`, so the runtime
  `liblgpio.so.1` is already there and only the unversioned `.so` symlink is
  missing — the build runs `swig`, compiles, and fails at the very last step on
  `ld: cannot find -llgpio`. Skip any of them and you get a venv that imports
  `gpiozero` happily and fails only when it first touches a pin.

  *(The alternative is to skip the build entirely and expose Pi OS's own
  `python3-lgpio` with a `--system-site-packages` venv. That would keep the
  compiler off the device, which is worth revisiting when the golden image is
  built in Phase 5. It is not done here because a self-contained venv means
  `uv run` behaves identically on the Pi and on a laptop, and every command in
  the docs is `uv run`.)*

- **`libspa-0.2-bluetooth` is installed.** It is PipeWire's Bluetooth backend
  and ships as its own package. Without it a speaker pairs and connects
  perfectly — BlueZ reports `Connected: yes` and resolves the A2DP Sink UUID —
  and no sink ever appears, so `Salida = Bluetooth` has nowhere to send audio.
  Every diagnostic you would reach for says Bluetooth is fine.

- **WirePlumber's seat monitoring is disabled.** This is the one that looks
  like witchcraft. WirePlumber starts its Bluetooth monitor only for a logind
  session that is `active` **on a seat** — a graphical login. A headless
  appliance never gets one, so the monitor loads, consults logind, and declines
  to start. Meanwhile BlueZ pairs, trusts, connects, and resolves the A2DP Sink
  UUID, so `bluetoothctl` reports a perfectly healthy connection while no sink
  ever appears in PipeWire and `Salida = Bluetooth` has nowhere to go.

- **SBC-XQ is preferred over plain SBC.** BlueZ negotiates ordinary SBC by
  default even when the speaker offers the higher-bitpool XQ variant, so
  without this every unit runs quieter and duller than the hardware allows —
  ~328 kbps where ~450 was available. Audibly better on choir and cymbals,
  which is most of this library. A speaker that does not offer XQ falls back
  to SBC by itself, so the preference is safe everywhere.

- **The verify step opens the GPIO chip**, rather than just importing
  `gpiozero`. Importing proves nothing; the failure above is invisible to it.

## What this does *not* do

Phase 4 hardening is deliberately out of scope — no read-only root, no systemd
service, no quiet boot. This produces a *bench* device: one you SSH into, run
the suite on, and drive by hand. See [BUILD-PLAN.md](../docs/BUILD-PLAN.md)
Phase 4 for what turns it into an appliance, and Phase 5 for why the golden
image, not this script, is what replicates across ten units.

## The original Zero W

The Zero **W** (v1.1, BCM2835) is not the Zero **2 W**: one ARM11 core at
1 GHz, no NEON, 32-bit only. It is a stand-in for demos while the Zero 2 W is
on order, not a production target. The same scripts provision it; three
things are different, all handled automatically:

- **32-bit image.** Flash Raspberry Pi OS Lite (32-bit). `provision.sh` reads
  `uname -m` and refuses anything that is not `armv6l`, `armv7l` or `aarch64`.
- **Pillow comes from piwheels.** Nobody publishes armv6 wheels except
  piwheels, and its newest cp311 build is 10.4 — so `app/pyproject.toml`
  pins Pillow `<10.5` on `armv6l` only and pulls it from there. Every other
  machine keeps PyPI and the unpinned line. The wheel links against distro
  libraries, which the script installs.
- **Video renders through the GPU.** `vo=drm` converts YUV to RGB on the CPU
  every frame; an ARM11 cannot do that at 720p. On `armv6l` the player uses
  `vo=gpu` on the DRM context so the VideoCore does the conversion. **This is
  untested at the time of writing.** Measure it:

  ```sh
  systemctl --user stop alabanza
  cd ~/alabanza/app
  ALABANZA_VIDEO="vo=gpu,gpu-context=drm,hwdec=v4l2m2m-copy" \
      uv run alabanza --gpio --oled-device --bt real
  ```

  `ALABANZA_VIDEO` replaces the whole mpv video option set (comma-separated,
  mpv's own names without the dashes) so decode paths can be compared without
  editing code. It is ignored when no display is connected.
- **It plays a 480p copy of the library.** A third of the pixels of 720p, and
  lyrics videos are text on a still background, so nothing a projector shows
  is lost. Build it once on the dev machine and push it instead of the 720p
  set:

  ```sh
  cd tools && uv run downscale_library.py       # library/ -> library-480/, ~5 min
  provision/sync.sh user@host --library-480     # ~1.2 GB instead of 2.3
  ```

  Same filenames, same `manifest.json`, so it is a drop-in for
  `alabanza --library`. `provision.sh` points the service at it automatically
  on `armv6l` when the folder is present, and warns when it is not. The
  audio is copied, not re-encoded, so durations and quality are unchanged.

Expect the first provision to take much longer than on the Pi 4: `dbus-fast`
compiles from source on one slow core — 28 minutes on the bench Zero W —
and falls back to pure Python if its C build fails, so a failure there is
slow, not fatal. `cbor2` and `lgpio` also come from piwheels for the same
reason: cbor2 6.x is a Rust extension and there is no Rust on the board.
Boot-to-ready is nearer a minute than the 10–15 s in the spec.

The current 32-bit Lite image is **Trixie with Python 3.13**, not Bookworm
with 3.11; the lock carries wheels for both. `provision.sh` also pins uv to
the system Python on `armv6l` (`UV_PYTHON_PREFERENCE=only-system`) because
uv has no managed CPython for that architecture and would otherwise stop at
"no download available". Run bench commands the same way:

```sh
export UV_PYTHON_PREFERENCE=only-system
```

Measured on a Zero W Rev 1.1 (Trixie, mpv 0.40, `vo=null` — decode and copy
only, no rendering), one hymn, 15 s of playback:

| File | `hwdec` | CPU | Dropped frames |
|---|---|---|---|
| 480p | `v4l2m2m-copy` | 21% | 0 |
| 720p | `v4l2m2m-copy` | 21% | 0 |
| 480p | software | 100% | 228 |

So the hardware decoder is mandatory and is not the bottleneck at either
size; what remains to measure is the render to HDMI through `vo=gpu`.

### Boot time

Measured before any of this: **2 min 9 s** from power to the user session,
then the app needed 15 s more before the panel lit. Where it went, and what
`provision.sh` now does about each (the "Trimming the boot" step, applied to
every board):

| Cost | Cause | Fix |
|---|---|---|
| 23 s | cloud-init re-running Imager's first-boot setup every boot | `/etc/cloud/cloud-init.disabled` |
| 44 s | NetworkManager rewriting 4 netplan profiles at start, each ending in a 6.6 s `daemon-reload` | the unused Ethernet profile is deleted on boards without `eth0` |
| ~50 s | the user session (PipeWire, the app) ordered after `network.target` | `systemd-user-sessions.service` copied to `/etc` without that ordering |
| 6 s | `NetworkManager-wait-online` | disabled |
| 15 s | `import mpv` (9 s: the linker resolving libmpv's 225 libraries) and the device imports, before the panel was opened | the app lights the panel first and imports afterwards |
| ~10 s | services an appliance never needs, all starting at once with logind: an LVM snapshot reaper (39 s of CPU), console keyboard setup, EEPROM update, and the daily apt / man-db / dpkg timers | disabled and masked |
| ~25 s | with the session no longer waiting, the app then shared the one core with NetworkManager, wpa_supplicant and the netplan reloads: 40 s to ready against 14 s alone | the user session gets 10× the CPU weight of system services, the network stack is niced, and on the Zero W NetworkManager is off the boot path: `alabanza-network.path` starts it when the app touches its ready marker (a 3-minute timer is the fallback for a crash-looping app) |

The device is never on the internet; Wi-Fi exists for the bench to SSH in
and push updates. On the Zero W that means SSH becomes available a minute
or two after power, after the panel, which is the right order for an
appliance. `systemctl start NetworkManager` brings it up sooner by hand.

The app now logs its milestones to the journal on every start, so a slow
boot can be read instead of guessed at:

```
journalctl --user -u alabanza -b | grep "alabanza:"
alabanza: panel up after 1.0s
alabanza: controls ready after 2.0s
alabanza: player ready after 10.2s
alabanza: ready after 13.8s (517 hymns)
```

`systemd-analyze critical-chain user@1000.service` shows the system side.

### Bluetooth audio

The first Bluetooth playback on the Zero W skipped constantly. Not the
radio: `pw-top` showed the Bluetooth sink node busy for **84–91% of every
graph cycle** with its underrun counter climbing, and WirePlumber (which
hosts that node) at 19% CPU. Two causes, both resampling on a core with
no NEON: PipeWire's graph runs at a fixed 48 kHz by default while the whole
library is 44.1 kHz, so mpv's stream was resampled up on the way in; and
the speaker had negotiated a 48 kHz link, so the node resampled back down
on the way out. `provision.sh` now sets both, in `/etc/pipewire` and the
WirePlumber Bluetooth config:

| Setting | Effect measured during a hymn on the speaker |
|---|---|
| graph at 44.1 kHz, allowed rates 44.1/48, quantum 2048 | node busy 5–23%, underruns 0, player 25% → 10% CPU |
| `bluez5.default.rate = 44100` (a 44.1 kHz A2DP link) | WirePlumber 19% → 7%, node busy 1–9%, box idle 20% → 43% |

It also gives PipeWire real-time priority without rtkit, which refuses a
headless session for the same seat reason WirePlumber's monitor did; the
audio threads had been running at ordinary priority, taking turns with the
app's Python threads.

**Speed changes** were the next thing to break, at the first church test:
nudging the speed made the hymn skip, and once the box reset. mpv keeps
the pitch across a speed change with `scaletempo2`, a floating-point
time-stretcher, and on this core that is far too much on top of a stream
that already costs ~63%. Measured playing a hymn to PipeWire, player
process only:

| Stretcher at 115% | CPU | Over the 100% baseline of 11% |
|---|---|---|
| `scaletempo2` (mpv's default, other boards) | 33% | +21 (+31 at 125%) |
| `scaletempo2` with a smaller search window | 36–38% | no better |
| `scaletempo` | 25% | +12 |
| `scaletempo=search=10` | 22% | +10 |
| `scaletempo=search=10` parked in the chain at 100% | 20% | +9 for nothing |

So on armv6l `player.py` puts `scaletempo=search=10` into the chain while
the speed is off 100% and takes it out again after. The journal of the
church boots shows two that ended without a shutdown sequence, i.e. a
power cut or a hardware reset, and nothing logged before them; with the
core no longer saturated the reset should not recur, but if it does, check
the supply first — `vcgencmd get_throttled` right after the next one.

### Idle CPU

The app is the other half of every boot number above: whatever it burns at
idle is what the network stack, Bluetooth and a hymn all have to share the
core with. Measured on the Zero W, idle on the home screen:

| Cost | Cause | Fix |
|---|---|---|
| ~20% | the panel re-drawn with PIL text rendering 20× a second, unchanged | an unchanged ViewModel is not drawn; a scrolling marquee still is |
| ~12% | keypad scan: three kernel line requests per row per pass through gpiozero, plus a 50 µs sleep that costs 190 µs | rows claimed once as open-drain outputs (the kernel's emulation is exactly the Hi-Z release), direct lgpio writes and reads, no sleep, 30 Hz |
| 12–15% | lgpio's alert thread, which every gpiozero `Button` and the `RotaryEncoder` need: it polls the event descriptors with a tiny timeout and costs this much with a single callback registered and no edges at all | the D-pad, push and wheel moved to the kernel's own drivers — next section |
| ~6% | the main loop at 20 Hz | — |

### Playing a hymn

Idle was half the story. With a hymn playing to the Bluetooth speaker the
app was at 86% and the panel thread alone at 47%, because most titles are
wider than the glass and the marquee re-rendered and re-sent the frame on
nearly every 50 ms tick, and because luma packs each frame into the
panel's page layout with a Python loop over all 8192 pixels (36 ms here,
more than drawing the frame). Three changes, measured during a hymn:

| Change | Panel thread | App total |
|---|---|---|
| before | 47% | 86% |
| frames compared at pixel resolution (progress rounds to the bar's 125 px) | 47% | 86% |
| marquee in 3 px steps at 8 fps instead of 1 px at 24 fps, identical frames skipped | 35% | 86% |
| the page buffer packed by PIL transforms instead of luma's loop (2 ms, was 36) | 22% | 63% |

The box now keeps a third of the core free while streaming, against 8%
before. mpv's seven built-in Lua scripts are also no longer loaded (OSC,
stats, console, ytdl, select, positioning, commands): seven idle threads
and about two seconds of startup on this core, for features a box with no
window or keyboard cannot use.

### Controls through the kernel

The 3×4 keypad is still scanned by the app (no stock overlay exists for a
matrix, and after the rewrite above it costs ~4%). The other seven controls
— D-pad, encoder push, encoder wheel — are handled by the kernel's
`gpio-keys` and `rotary-encoder` drivers, loaded from the stock overlays
`provision.sh` appends to `config.txt`:

```
dtoverlay=rotary-encoder,pin_a=17,pin_b=27,relative_axis=1,steps-per-period=2
dtoverlay=gpio-key,gpio=22,keycode=139,label=alabanza-push
dtoverlay=gpio-key,gpio=23,keycode=28,label=alabanza-centre
…
```

They are interrupt-driven and deliver a 16-byte record per key edge or
wheel step on `/dev/input/event*`; the app's thread sleeps in `select()`
between them (`app/alabanza/input_evdev.py`). Debounce and the hold
timings are done in the app, in a pure class with laptop tests, so both
backends behave the same. Discovery is by bus and capability: a host-bus
device advertising our key codes or a relative X axis. The bus check
matters — the vc4 HDMI CEC device and a Bluetooth speaker's AVRCP remote
both advertise those keys, and matching them left the real D-pad dead.

If the overlays are not loaded (a board provisioned before this, or a
config.txt edit lost), the app logs *kernel input devices not found* and
falls back to gpiozero, so nothing stops working; it just costs the alert
thread again.

Two things need the bench, once per encoder part: `steps-per-period` (one
click of the EC11 must produce exactly one wheel event — the fitted part
gave two events per five clicks in full-period mode, hence 2) and
`WHEEL_SIGN` in `input_evdev.py` (clockwise must be clockwise; it depends
on which channel is wired as A — verified +1 on this board). Watch the raw
stream with:

```sh
systemctl --user stop alabanza
cd ~/alabanza/app && uv run python -c "
from alabanza.input_evdev import *; import os, select, time
fds = {os.open(n, os.O_RDONLY|os.O_NONBLOCK): str(n) for n in discover()}
print(discover()); 
while True:
    r,_,_ = select.select(list(fds), [], [], 1)
    for fd in r:
        for t,c,v in decode(os.read(fd, 1024)):
            if t: print(time.monotonic() % 100, fds[fd], 'type', t, 'code', c, 'value', v)"
```

Tier 2 (`pytest -m device`) no longer claims those seven pins — the kernel
owns them — and checks instead that the input devices exist and advertise
every control.
