# Alabanza

A Raspberry Pi–based hymn player appliance for church use: 517 hymns, selected
by number on a keypad, played to a headphone jack, Bluetooth speaker, or HDMI
(lyrics videos on the projector). Operated entirely through an OLED display
and physical controls. Battery powered, fully portable.

- **[docs/SPEC.md](docs/SPEC.md)** — what the device is; every design decision and why
- **[docs/BUILD-PLAN.md](docs/BUILD-PLAN.md)** — how it gets built: phases, BOM, GPIO pin map, production run

## Repo layout

| Path | What |
|---|---|
| `app/` | The player application (Python, runs on the Pi and on a dev machine) |
| `tools/` | Library tooling: YouTube downloader + provisioning script |
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
```

Keys: digits + Enter play a hymn by number, `/` opens T9 title search,
Space pause, `s` stop, arrows seek/browse, `-`/`+` speed, `m` menu, `q` quit.
