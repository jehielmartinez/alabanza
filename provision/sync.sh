#!/usr/bin/env bash
#
# Alabanza — push this working copy to a device.
#
# Run it on the DEV MACHINE (not the Pi):
#
#     provision/sync.sh jehiel@192.168.1.109            # code only, fast
#     provision/sync.sh jehiel@192.168.1.109 --library  # code + the 2.3 GB library
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
    echo "usage: $0 user@host [--library]" >&2
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

if [ "${2:-}" != "--library" ]; then
    EXCLUDES+=(--exclude 'tools/library/' --exclude 'tools/downloads/')
fi

# Portable flags only. macOS ships openrsync (advertised as "2.6.9
# compatible"), which rejects --info=stats1 and most other modern rsync
# options; the script has to run from a Mac, so it sticks to the old set.
echo "==> syncing $REPO -> $TARGET:$DEST"
rsync -az --delete "${EXCLUDES[@]}" "$REPO/" "$TARGET:$DEST/"

echo "==> done"
if [ "${2:-}" != "--library" ]; then
    echo "    (library excluded — pass --library to include it)"
fi
