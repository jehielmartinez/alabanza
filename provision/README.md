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
