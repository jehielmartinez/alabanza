# Alabanza

A Raspberry Pi–based hymn player appliance for church use: 517 hymns, selected
by number on a keypad, played to a headphone jack, Bluetooth speaker, or HDMI
(lyrics videos on the projector). Operated entirely through an OLED display
and physical controls. Battery powered, fully portable.

- **[docs/SPEC.md](docs/SPEC.md)** — what the device is; every design decision and why
- **[docs/BUILD-PLAN.md](docs/BUILD-PLAN.md)** — how it gets built: phases, BOM, GPIO pin map, production run
- **[docs/HARDWARE.md](docs/HARDWARE.md)** — the custom control PCB: schematic blocks, layout rules, pre-fab checklist
- **[docs/BLUETOOTH.md](docs/BLUETOOTH.md)** — Phase 2 design: BT architecture, screen flows, audio routing
- **[docs/TESTING.md](docs/TESTING.md)** — what is tested where, from the laptop suite to per-unit acceptance

## Repo layout

| Path | What |
|---|---|
| `app/` | The player application (Python, runs on the Pi and on a dev machine) |
| `tools/` | Library tooling: YouTube downloader, provisioning script, Bible converter |
| `docs/` | Specification and build plan |

## ⚠ The hymn library is NOT in this repo

The media (~2.3 GB of MP4s) is git-ignored. The app expects the provisioned
library — the MP4 files plus `manifest.json` — at **`tools/library/`**
(the default), or anywhere else via `alabanza --library <dir>`.

To rebuild the library from scratch on a new machine:

```sh
cd tools
uv run download_hymns.py      # downloads all playlists in playlists.txt
                              # (needs YouTube cookies in Chrome; resumable, re-run until done)
uv run provision_library.py   # downloads/ -> library/ with canonical names + manifest.json
```

If you already have the `library/` folder (e.g. copied from another machine or
the golden SD image), just place it at `tools/library/` and nothing needs
downloading.

## Running the app (dev)

Requires [uv](https://docs.astral.sh/uv/) and libmpv (`brew install mpv` on
macOS; `apt install libmpv2` on Raspberry Pi OS).

```sh
cd app
uv run alabanza              # terminal UI, keyboard stands in for the controls
uv run alabanza --no-video   # audio only
uv run alabanza --oled       # also show the exact 128x64 OLED pixels
uv run alabanza --bt none    # pretend there is no bluetooth adapter
```

The device has a 3×4 keypad, a 5-way D-pad and a rotary encoder — nothing else.
The keyboard stands in for them:

| Key | Control |
|---|---|
| `0`–`9`, `*`, `#` | keypad — number, back/stop, play |
| `Space`, `←` `→`, `↑` `↓` | D-pad — centre, seek, up/down |
| `-` `+` | encoder wheel (volume while playing, browse while idle) |
| `m` | encoder push (opens the menu) |
| `r`, `q` | rescan, quit (dev only) |

`↑`/`↓` change the speed while a hymn plays and browse the library when it
doesn't; T9 title search lives in the menu — predictive, one press per
letter, so `Cielo` is `2 4 3 5 6`.

The menu also has **Biblia**: verses on the projector, white on black —
pick a book (turn, or T9 on its name), a chapter and a verse; then the wheel
follows the reading, `#` adds the next verse to the slide and `*` takes it
off. Design in **[docs/BIBLE.md](docs/BIBLE.md)**. The text is not in the
repo either; build it once:

```sh
cd tools
uv run build_bible.py         # downloads the RVR1960 -> tools/bible/rvr1960/
```

## Tests

```sh
cd app
uv run --extra test pytest      # ~130 tests, 0.1s; hardware tests deselect themselves
```

Full strategy — including the on-device, endurance and per-unit tiers — in
**[docs/TESTING.md](docs/TESTING.md)**.

## Bluetooth on a laptop

Bluetooth runs against a **fake backend** by default off-device — scripted
speakers with realistic latencies, one that drops mid-hymn and one that never
answers, so the failure paths can be rehearsed on a laptop. `m` → `Bluetooth`.
On the Pi, `--bt real` talks to BlueZ.
