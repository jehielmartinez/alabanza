#!/usr/bin/env bash
#
# Alabanza — turn a fresh Raspberry Pi OS Lite install into a working device.
#
# Run it ON the Pi, from anywhere inside a checkout of this repo:
#
#     provision/provision.sh                # appliance: starts at boot
#     provision/provision.sh --no-headless  # bench: start it by hand
#
# It is **idempotent**. Re-running it is the supported way to repair a unit or
# to pick up a change, and it is how all ten units get the same configuration
# rather than ten slightly different ones (BUILD-PLAN.md Phase 5).
#
# By default the unit is enabled, so the box comes up playing hymns with no
# login — which is the product. That also means it owns the GPIO and the
# panel from boot, so `pytest -m device` and `alabanza-hwtest` will report
# 'GPIO busy' until the service is stopped. Use --no-headless while bringing
# a board up, or stop it: `systemctl --user stop alabanza`.
#
# It still does NOT do the rest of Phase 4 hardening — read-only root and
# quiet boot are deliberately absent.

set -euo pipefail

ENABLE_AUTOSTART=1
for arg in "$@"; do
    case "$arg" in
        --no-headless)
            ENABLE_AUTOSTART=0 ;;
        -h|--help)
            sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^#//; s/^ //'; exit 0 ;;
        *)
            printf 'unknown option: %s (try --help)\n' "$arg" >&2; exit 2 ;;
    esac
done

# i2cdetect and rfkill live in /usr/sbin, which is absent from PATH in a
# non-login shell — exactly what `ssh host '...'` gives you. Without this the
# verify step below silently skips the OLED check instead of running it.
PATH="$PATH:/usr/sbin"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$REPO/app"
UV="$HOME/.local/bin/uv"

step()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$1"; }
ok()    { printf '    \033[32mok\033[0m   %s\n' "$1"; }
warn()  { printf '    \033[33mwarn\033[0m %s\n' "$1"; }
die()   { printf '\n\033[31merror:\033[0m %s\n\n' "$1" >&2; exit 1; }

# --- 0. sanity ------------------------------------------------------------

step "Checking the host"

MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)"
case "$MODEL" in
    *"Raspberry Pi"*) ok "$MODEL" ;;
    *) die "this is not a Raspberry Pi (model: $MODEL). Run it on the device." ;;
esac

# The Pi 5 / 500 is a deliberate non-target: no hardware H.264 decoder and GPIO
# behind RP1. See BUILD-PLAN.md "Prototyping hardware".
case "$MODEL" in
    *"Pi 5"*|*"Pi 500"*)
        warn "Pi 5-class board. Fine for the app, but decode and GPIO behaviour"
        warn "do not match the Zero 2 W — do not tune mpv or GPIO here." ;;
esac

[ -f "$APP/pyproject.toml" ] || die "no app/ found next to this script — is the repo complete?"

# sudo up front, so the password prompt happens now rather than halfway through
sudo -v || die "this script needs sudo"

# --- 1. board configuration ----------------------------------------------

step "Configuring the board"

# I2C on: the SSD1309 lives at 0x3C on bus 1 (BUILD-PLAN.md pin map).
if [ "$(sudo raspi-config nonint get_i2c)" = "0" ]; then
    ok "I2C already enabled"
else
    sudo raspi-config nonint do_i2c 0
    ok "I2C enabled"
fi

# I2C at 400 kHz rather than the 100 kHz default. The OLED is 1 KB per frame,
# which is ~96 ms at 100 kHz -- and the app renders in the same loop that scans
# the keypad, so a slow panel is a keypad that misses presses. 400 kHz is
# within the SSD1309's spec and cuts that to ~24 ms.
if grep -qE '^dtparam=i2c_arm_baudrate=400000' /boot/firmware/config.txt; then
    ok "I2C already at 400 kHz"
else
    sudo sed -i '/^dtparam=i2c_arm_baudrate=/d' /boot/firmware/config.txt
    echo 'dtparam=i2c_arm_baudrate=400000' | sudo tee -a /boot/firmware/config.txt >/dev/null
    warn "I2C set to 400 kHz — takes effect after a reboot"
fi

# SPI OFF, and this is not cosmetic: BCM 7 and 8 are CE1/CE0. With SPI enabled
# the kernel owns those two lines, lgpio cannot claim them, and the D-pad's
# up/down keys are dead while the other three work perfectly — an asymmetry
# that reads as a wiring fault and is not one.
if [ "$(sudo raspi-config nonint get_spi)" = "1" ]; then
    ok "SPI already disabled (BCM 7/8 free for the D-pad)"
else
    sudo raspi-config nonint do_spi 1
    ok "SPI disabled — BCM 7/8 released for the D-pad"
fi

# Persistent, bounded journald. Pi OS ships
# /usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf, which keeps
# the journal in /run -- so it is RAM only, it is lost on every reboot, and
# journald creates no per-user journal at all, which is why
# `journalctl --user -u alabanza` answers "No journal files were found" on a
# stock image. The app logs through StandardOutput=journal, so a unit that
# died overnight leaves nothing to read in the morning: exactly the evidence
# a ten-unit fleet in ten different churches cannot be debugged without.
#
# The vendor default is not wrong, it is a trade -- SD cards wear out -- so
# this takes the logs and keeps the trade explicit: 32 MB total, 8 MB per
# file. Bounded like that, rotation is cheap and the card is not the thing
# paying for it. 50- beats 40- whichever directory it is read from.
#
# Phase 4's read-only root will need /var/log/journal bind-mounted onto the
# writable partition, or this quietly goes back to being volatile.
JOURNAL_CONF=/etc/systemd/journald.conf.d/50-alabanza-persistent.conf
# `journalctl --user` exits 0 even when it finds no journal files at all, so
# the obvious probe passes on exactly the box that is broken. Whether
# persistent storage actually produced a file is the honest question.
if [ -f "$JOURNAL_CONF" ] && ls /var/log/journal/*/system.journal >/dev/null 2>&1; then
    ok "journal already persistent"
else
    sudo mkdir -p /etc/systemd/journald.conf.d
    sudo tee "$JOURNAL_CONF" >/dev/null <<'JCONF'
# Alabanza: keep the logs across reboots, and keep per-user journals so
# `journalctl --user -u alabanza` works -- see provision/README.md.
[Journal]
Storage=persistent
SystemMaxUse=32M
SystemMaxFileSize=8M
JCONF
    sudo mkdir -p /var/log/journal
    sudo systemd-tmpfiles --create --prefix /var/log/journal >/dev/null 2>&1 || true
    sudo systemctl restart systemd-journald
    sudo journalctl --flush >/dev/null 2>&1 || true
    # One entry as this user, which both records when the unit was
    # provisioned and forces the per-user journal into existence -- until
    # something logs as uid 1000 there is no user-1000.journal for
    # `journalctl --user` to open, and its absence looks like the
    # configuration did not take.
    systemd-cat -t alabanza-provision echo "provisioned $(date -Is)" || true
    if ls /var/log/journal/*/user-*.journal >/dev/null 2>&1; then
        ok "journal is persistent and per-user, capped at 32M"
    else
        warn "journal set to persistent but no per-user journal appeared yet"
    fi
fi

# --- 2. system packages ---------------------------------------------------

step "Installing system packages"

# libmpv2      what python-mpv binds to; the playback engine
# i2c-tools    i2cdetect, which tests/test_device.py shells out to
# swig, python3-dev, build-essential, liblgpio-dev
#              PyPI lgpio is a C extension and will NOT build without all four.
#              liblgpio-dev is the easy one to miss: Pi OS preinstalls
#              liblgpio1, so the runtime .so.1 is present and only the
#              unversioned .so symlink the linker wants is absent — the build
#              gets all the way to `ld` before failing on `-llgpio`.
#              Leaving any of them out yields a venv that imports gpiozero
#              fine and fails only when it first touches a pin.
# pipewire, pipewire-audio, pipewire-pulse, wireplumber, pulseaudio-utils
#              Pi OS Lite ships no sound server at all. Without one the USB
#              DAC and the Bluetooth sink cannot be selected, so every audio
#              route in SPEC.md is unreachable. pulseaudio-utils is easy to
#              leave out and looks unrelated: pipewire-pulse supplies the
#              PulseAudio *server* protocol, while `pactl` -- the client the
#              tests and any manual debugging use -- ships separately.
# libspa-0.2-bluetooth
#              PipeWire's Bluetooth backend, and its own package. Without it
#              a speaker pairs and connects perfectly -- BlueZ reports
#              Connected: yes and resolves the A2DP Sink UUID -- and then no
#              sink ever appears, so Salida = Bluetooth silently has nowhere
#              to send audio. The Bluetooth half looks healthy from every
#              angle except the one that matters.
# rfkill       needed to clear the Bluetooth soft block below
# rsync, git   getting the repo and the library onto the box
PACKAGES=(libmpv2 i2c-tools swig python3-dev build-essential liblgpio-dev
          pipewire pipewire-audio pipewire-pulse wireplumber pulseaudio-utils
          libspa-0.2-bluetooth rfkill rsync git)

MISSING=()
for pkg in "${PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING+=("$pkg")
done

if [ ${#MISSING[@]} -eq 0 ]; then
    ok "all present"
else
    printf '    installing: %s\n' "${MISSING[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${MISSING[@]}"
    ok "installed ${#MISSING[@]} package(s)"
fi

# --- 3. group membership --------------------------------------------------

step "Checking group membership"

NEEDED_GROUPS=(gpio i2c audio video)
ADDED=0
for grp in "${NEEDED_GROUPS[@]}"; do
    if id -nG "$USER" | tr ' ' '\n' | grep -qx "$grp"; then
        ok "$USER is in $grp"
    else
        sudo usermod -aG "$grp" "$USER"
        warn "added $USER to $grp — log out and back in for it to take effect"
        ADDED=1
    fi
done

# --- 3b. audio and bluetooth services -------------------------------------

step "Enabling audio and Bluetooth"

# PipeWire is a *user* service. Without lingering it only runs while someone
# is logged in, so audio works over SSH and dies the moment you disconnect --
# which reads as "Bluetooth broke overnight" rather than "no session".
sudo loginctl enable-linger "$USER" 2>/dev/null || true
systemctl --user enable --now pipewire pipewire-pulse wireplumber 2>/dev/null || true
if systemctl --user is-active --quiet pipewire; then
    ok "pipewire running"
else
    warn "pipewire not active yet — it starts on next login"
fi

# A fresh image ships the controller soft-blocked (bluetoothctl reports
# PowerState: off-blocked), and BlueZ leaves controllers powered down unless
# told otherwise. SPEC.md's "auto-reconnect at boot to the last-used speaker"
# needs the adapter up *before* the app starts, so both are fixed here.
sudo rfkill unblock bluetooth 2>/dev/null || true

if grep -qE '^[[:space:]]*AutoEnable[[:space:]]*=[[:space:]]*true' /etc/bluetooth/main.conf; then
    ok "BlueZ AutoEnable already set"
else
    sudo sed -i 's/^#[[:space:]]*AutoEnable[[:space:]]*=.*/AutoEnable=true/' /etc/bluetooth/main.conf
    grep -qE '^[[:space:]]*AutoEnable[[:space:]]*=[[:space:]]*true' /etc/bluetooth/main.conf \
        || sudo sed -i '/^\[Policy\]/a AutoEnable=true' /etc/bluetooth/main.conf
    ok "BlueZ AutoEnable=true — controller powers on at boot"
fi

sudo systemctl enable --now bluetooth >/dev/null 2>&1 || true
sudo systemctl restart bluetooth >/dev/null 2>&1 || true

# WirePlumber gates its Bluetooth monitor on logind *seat* state and starts it
# only for a session that is `active` on a seat. This appliance has no display
# manager and no graphical login, so its session sits at `online` forever and
# the monitor loads, asks logind, and quietly declines to start. The symptom is
# perfect: BlueZ pairs, trusts, connects and resolves the A2DP Sink UUID, and
# no sink ever appears in PipeWire. Nothing in the Bluetooth stack looks wrong.
sudo mkdir -p /etc/wireplumber/wireplumber.conf.d
sudo tee /etc/wireplumber/wireplumber.conf.d/50-alabanza-headless.conf >/dev/null <<'WPCONF'
# Alabanza runs headless with no seat, ever. Without this there is no
# Bluetooth audio -- see provision/README.md.
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
WPCONF
ok "WirePlumber seat-monitoring disabled — Bluetooth audio can start headless"

# Prefer SBC-XQ over plain SBC. Both are SBC; XQ simply uses a much higher
# bitpool (~450 kbps against ~328) and is audibly better on choir and cymbals,
# which is most of the library. BlueZ negotiates plain SBC by default even
# when the speaker offers XQ, so without this every unit quietly runs at the
# lower quality. Verified by ear on the bench speaker.
#
# The list is ordered: a speaker that does not offer XQ falls back to SBC on
# its own, so this is safe for whatever the church actually owns.
sudo tee /etc/wireplumber/wireplumber.conf.d/51-alabanza-bluetooth-codec.conf >/dev/null <<'WPCODEC'
# Alabanza: prefer the higher-bitpool SBC variant -- see provision/README.md.
monitor.bluez.properties = {
  bluez5.enable-sbc-xq = true
  bluez5.codecs = [ sbc_xq sbc aac ]
}
WPCODEC
ok "Bluetooth codec preference: SBC-XQ before SBC"

# WirePlumber starts every new sink at 40% -- its own default, and about 24 dB
# of attenuation before a sample leaves the Pi. On this device that is silently
# wrong: the encoder is the volume control, the app's 100% should mean 100%,
# and the operator's only recourse otherwise is to turn the speaker up until
# the noise floor comes with it. Sinks start at unity; the encoder does the
# attenuating.
sudo tee /etc/wireplumber/wireplumber.conf.d/52-alabanza-volume.conf >/dev/null <<'WPVOL'
# Alabanza: new sinks at full scale -- volume belongs to the encoder.
wireplumber.settings = {
  device.routes.default-sink-volume = 1.0
}
WPVOL
ok "new sinks default to 100%"

# Existing sinks keep whatever WirePlumber stored for them, so fix them too.
for sink in $(pactl list sinks short 2>/dev/null | cut -f1); do
    pactl set-sink-volume "$sink" 100% 2>/dev/null || true
done
ok "existing sinks set to 100%"

# Installing SPA plugins does not make a running PipeWire notice them, so the
# stack is restarted after packages, not before.
systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null || true
sleep 2

# --- 4. python environment ------------------------------------------------

step "Setting up the Python environment"

if [ ! -x "$UV" ] && ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    ok "installed uv"
fi
command -v uv >/dev/null && UV="$(command -v uv)"
[ -x "$UV" ] || die "uv install failed"
ok "$("$UV" --version)"

cd "$APP"
"$UV" sync --extra test --extra device --quiet
ok "venv ready at app/.venv"

# --- 4b. autostart and shutdown -------------------------------------------

step "Installing the service"

# The app runs as a user service, not a system one. It needs the user's
# PipeWire session for audio, and a system service would have none -- the same
# session that `loginctl enable-linger` above keeps alive without a login.
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/alabanza.service" <<UNIT
[Unit]
Description=Alabanza hymn player
After=pipewire.service bluetooth.target
Wants=pipewire.service

[Service]
Type=simple
WorkingDirectory=$APP
ExecStart=$UV run --no-sync --extra device alabanza --gpio --oled-device --bt real
Restart=always
RestartSec=3
# The panel is the only interface; nothing should reach the console, which
# under SPEC decision 8 is a projector.
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
ok "alabanza.service written"

# Powering off from the menu, or by holding the encoder. The app is not root,
# so it needs exactly one command and nothing else. Narrow on purpose: this
# file is the whole privilege the appliance is given.
sudo tee /etc/sudoers.d/alabanza-poweroff >/dev/null <<SUDOERS
$USER ALL=(root) NOPASSWD: /sbin/poweroff
SUDOERS
sudo chmod 440 /etc/sudoers.d/alabanza-poweroff
ok "poweroff permitted for $USER (that command only)"

# --- 5. verify ------------------------------------------------------------

step "Verifying"

FAILED=0

if [ -e /dev/i2c-1 ]; then
    ok "/dev/i2c-1 present"
else
    warn "/dev/i2c-1 missing — a reboot is needed for the I2C change to apply"
    FAILED=1
fi

# gpiozero must not merely import: it has to reach a pin. This is the check
# that catches a missing lgpio build, which is otherwise invisible until the
# first keypress.
if "$UV" run --no-sync python -c "
from gpiozero import Device
from gpiozero.pins.lgpio import LGPIOFactory
Device.pin_factory = LGPIOFactory()
print('    pin factory:', Device.pin_factory.__class__.__name__)
" 2>/dev/null; then
    ok "gpiozero can open the GPIO chip"
else
    warn "gpiozero cannot open a pin — lgpio is missing or the build failed"
    FAILED=1
fi

if "$UV" run --no-sync python -c "import mpv" 2>/dev/null; then
    ok "python-mpv found libmpv"
else
    warn "python-mpv cannot load libmpv — is libmpv2 installed?"
    FAILED=1
fi

if command -v i2cdetect >/dev/null && [ -e /dev/i2c-1 ]; then
    if i2cdetect -y 1 2>/dev/null | grep -q '3c'; then
        ok "OLED answering at 0x3c"
    else
        warn "nothing at 0x3c — expected if the panel is not wired up yet"
    fi
fi

# --- 6. autostart ---------------------------------------------------------
#
# Last on purpose. The verify step above opens the GPIO chip, and an already
# running service holds those lines -- enabling any earlier makes provisioning
# report 'GPIO busy' on a perfectly good board, which is a full evening of
# chasing a fault that does not exist.

step "Autostart"

if [ "$ENABLE_AUTOSTART" = "1" ]; then
    systemctl --user enable --now alabanza >/dev/null 2>&1
    sleep 3
    if systemctl --user is-active --quiet alabanza; then
        # Type=simple reports "active" the instant the process is spawned, so
        # a crash loop looks healthy through `is-active` alone -- it keeps
        # landing in the RestartSec gap. NRestarts is the honest number.
        RESTARTS="$(systemctl --user show alabanza -p NRestarts --value)"
        if [ "${RESTARTS:-0}" = "0" ]; then
            ok "alabanza.service enabled and running (starts at boot)"
        else
            warn "alabanza.service is restarting ($RESTARTS so far) — it is"
            warn "crash-looping. journalctl --user -u alabanza -n 50"
            FAILED=1
        fi
    else
        warn "alabanza.service did not start; journalctl --user -u alabanza"
        FAILED=1
    fi
else
    systemctl --user disable --now alabanza >/dev/null 2>&1 || true
    ok "alabanza.service installed but NOT enabled (--no-headless)"
fi

# --- done -----------------------------------------------------------------

step "Done"

if [ "$ADDED" = "1" ]; then
    warn "group changes need a fresh login: exit and SSH back in."
fi
if [ "$FAILED" != "0" ]; then
    warn "something above needs attention; a reboot fixes most of it."
fi

if [ "$ENABLE_AUTOSTART" = "1" ]; then
    cat <<'NEXT'

    This box is an appliance now: it starts at boot with no login, and the
    panel is the only interface.

      journalctl --user -u alabanza -f           # watch it
      systemctl --user stop alabanza             # hand the GPIO back
      systemctl --user disable --now alabanza    # ...and stop it doing that at boot

    The service owns the GPIO and the panel, so stop it before any of the
    bench commands below — otherwise they report 'GPIO busy' and it reads
    like a wiring fault.

NEXT
else
    cat <<'NEXT'

    Autostart is installed but NOT enabled, so the GPIO and the panel stay
    free for bench work. Turn it on when the unit is ready to be a product:

      systemctl --user enable --now alabanza     # start at boot
      journalctl --user -u alabanza -f           # watch it

NEXT
fi

cat <<'NEXT'
    Bench commands:
      cd app
      uv run --extra test pytest                       # Tier 1: logic, no hardware
      uv run --extra test --extra device pytest -m device   # Tier 2: is it wired?
      uv run alabanza-hwtest                           # Tier 2b: press every control
      uv run alabanza --gpio --oled-device --bt real   # drive it by hand

    Tier 2 failures name the pin, not the symptom. See docs/TESTING.md.

    Tier 2b is the one to run on a freshly built board. Tier 2 proves a pin
    can be claimed; only a finger proves the key marked 7 reports a 7, which
    is what catches a swapped row or a mirrored connector. It draws on the
    OLED, so it exercises the panel at the same time.

NEXT
