# Provisioning

Two scripts, one job each. Together they take a **fresh Raspberry Pi OS Lite
install** to a bench device you can run hymns on.

| Script | Runs on | What |
|---|---|---|
| `sync.sh` | the dev machine | mirror this working copy onto the Pi |
| `provision.sh` | the Pi | configure the board, install everything, verify |

## From a blank SD card

1. **Flash** Raspberry Pi OS **Lite (64-bit)** with Raspberry Pi Imager. Do not
   format the card in Disk Utility first — Imager writes its own partition
   table. In Imager's settings, set the hostname, create the user, and **enable
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
   ```

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

- **The verify step opens the GPIO chip**, rather than just importing
  `gpiozero`. Importing proves nothing; the failure above is invisible to it.

## What this does *not* do

Phase 4 hardening is deliberately out of scope — no read-only root, no systemd
service, no quiet boot. This produces a *bench* device: one you SSH into, run
the suite on, and drive by hand. See [BUILD-PLAN.md](../docs/BUILD-PLAN.md)
Phase 4 for what turns it into an appliance, and Phase 5 for why the golden
image, not this script, is what replicates across ten units.
