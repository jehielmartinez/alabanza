#!/usr/bin/env bash
#
# Alabanza — push this working copy to a device.
#
# Run it on the DEV MACHINE (not the Pi):
#
#     provision/sync.sh jehiel@192.168.1.109                # code only, fast
#     provision/sync.sh jehiel@192.168.1.109 --library      # code + the 2.3 GB library
#     provision/sync.sh jehiel@192.168.1.109 --library-480  # code + the 480p copy (Zero W)
#
# Code-only is the loop you want while developing: it is a couple of seconds,
# so "edit on the laptop, run on the Pi" stays comfortable. The library is
# large and effectively immutable, so it is opt-in and only needed once.
#
# Deletes remote files that no longer exist locally, so the Pi is a mirror of
# the working copy rather than an accumulation of every version ever pushed.

set -euo pipefail

TARGET="${1:-}"
[ -n "$TARGET" ] || {
    echo "usage: $0 user@host [--library|--library-480]" >&2
    exit 1
}
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ALABANZA_DEST:-~/alabanza}"

# Never sync build artefacts or virtualenvs: app/.venv holds Linux binaries on
# the Pi and macOS ones here, and copying one over the other produces a venv
# that fails in a way nobody enjoys diagnosing.
EXCLUDES=(
    --exclude '.git/'
    --exclude '.venv/'
    --exclude '__pycache__/'
    --exclude '.pytest_cache/'
    --exclude '.ruff_cache/'
    --exclude '.DS_Store'
)

# -z earns its keep on source but is actively harmful on the library: MP4s
# are already compressed, so gzip finds nothing and both CPUs become the
# bottleneck on what should be a network-bound copy. --partial matters over
# WiFi, where losing 2 GB at 95% and starting again is a real outcome.
# Every library folder is excluded unless asked for, and only the one asked
# for goes: the Zero W wants the 480p copy and has no room or time for both.
FLAGS=(-az --delete)
EXCLUDES+=(--exclude 'tools/downloads/')

# The Bible text (tools/bible/, 5 MB) is small enough to ride along on every
# sync, so it does. But it is git-ignored like the hymns, so a fresh clone
# does not have it -- and with --delete, syncing from such a clone would
# erase the copy already on the device and leave the menu row saying "Sin
# Biblia en la tarjeta". Absent here means "leave the device's alone".
[ -d "$REPO/tools/bible" ] || EXCLUDES+=(--exclude 'tools/bible/')
case "${2:-}" in
    --library)
        FLAGS=(-a --delete --partial)
        EXCLUDES+=(--exclude 'tools/library-480/') ;;
    --library-480)
        FLAGS=(-a --delete --partial)
        EXCLUDES+=(--exclude 'tools/library/') ;;
    "")
        EXCLUDES+=(--exclude 'tools/library/' --exclude 'tools/library-480/') ;;
    *)
        echo "unknown option: $2 (try --library or --library-480)" >&2; exit 1 ;;
esac

# Portable flags only. macOS ships openrsync (advertised as "2.6.9
# compatible"), which rejects --info=stats1 and most other modern rsync
# options; the script has to run from a Mac, so it sticks to the old set.
echo "==> syncing $REPO -> $TARGET:$DEST"
rsync "${FLAGS[@]}" "${EXCLUDES[@]}" "$REPO/" "$TARGET:$DEST/"

echo "==> done"
if [ -z "${2:-}" ]; then
    echo "    (library excluded — pass --library or --library-480 to include one)"
fi
