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

# The original Zero W (BCM2835, one ARM11 core, armv6l) is a demo stand-in
# for the Zero 2 W, not a production target. It needs the 32-bit image, gets
# Pillow from piwheels instead of a source build, and renders video through
# a different mpv chain (app/alabanza/player.py). Same header, same pins.
ARCH="$(uname -m)"
if [ "$ARCH" = "armv6l" ]; then
    warn "armv6l: the original Zero W. Expect a slow first provision and"
    warn "measure video before trusting it — see provision/README.md."
fi
case "$ARCH" in
    armv6l|armv7l|aarch64) ;;
    *) die "unexpected architecture $ARCH — is this the right OS image?" ;;
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

# The D-pad, the encoder push and the wheel are read through the kernel's
# gpio-keys and rotary-encoder drivers rather than gpiozero: interrupt
# driven, delivered on /dev/input, and free of lgpio's alert thread, which
# cost the Zero W 12-15% of its core for nothing. The key codes are the
# ones app/alabanza/input_evdev.py expects; the pins are pins.py. Defaults
# of gpio-key are active-low with the internal pull-up, which is how every
# switch is wired (HARDWARE.md). steps-per-period is a property of the
# EC11 fitted: this one has two detents per quadrature period, measured on
# the bench -- five clicks gave two events in full-period mode -- so 2, and
# one click is one event. A different encoder batch may want 1 or 4.
CONFIG=/boot/firmware/config.txt
if grep -q '^dtoverlay=rotary-encoder,pin_a=17,pin_b=27,relative_axis=1,steps-per-period=2' "$CONFIG"; then
    ok "control overlays already in config.txt"
else
    sudo sed -i '/^# Alabanza controls/,/^# end Alabanza controls/d' "$CONFIG"
    sudo tee -a "$CONFIG" >/dev/null <<'OVERLAYS'
# Alabanza controls: kernel input drivers for the D-pad, push and wheel.
# Managed by provision/provision.sh -- edit there, not here.
[all]
dtoverlay=rotary-encoder,pin_a=17,pin_b=27,relative_axis=1,steps-per-period=2
dtoverlay=gpio-key,gpio=22,keycode=139,label=alabanza-push
dtoverlay=gpio-key,gpio=23,keycode=28,label=alabanza-centre
dtoverlay=gpio-key,gpio=25,keycode=105,label=alabanza-left
dtoverlay=gpio-key,gpio=26,keycode=106,label=alabanza-right
dtoverlay=gpio-key,gpio=7,keycode=103,label=alabanza-up
dtoverlay=gpio-key,gpio=8,keycode=108,label=alabanza-down
# end Alabanza controls
OVERLAYS
    warn "control overlays added to config.txt — take effect after a reboot"
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

# --- 1b. boot time --------------------------------------------------------
#
# Measured on the Zero W: 2 min 9 s from power to the user session, and the
# app cannot start before the session does. Three things own most of it,
# none of them needed by an appliance, and all of them are ~10x cheaper on a
# Pi 4 which is why nobody noticed there.

step "Trimming the boot"

# cloud-init is how Raspberry Pi Imager applies the user, hostname, Wi-Fi
# and SSH key on the very first boot, and Pi OS keeps running it on every
# boot after that: 23 s of the sysinit critical chain on the Zero W, doing
# nothing. The documented off switch is this file. The settings it applied
# are already persisted (netplan yaml, NM keyfiles), so it is safe once
# `cloud-init status` says done -- which it has by the time this runs.
if [ -d /etc/cloud ]; then
    if [ -e /etc/cloud/cloud-init.disabled ]; then
        ok "cloud-init already disabled"
    else
        sudo touch /etc/cloud/cloud-init.disabled
        ok "cloud-init disabled — it had finished its first-boot job"
    fi
fi

# NetworkManager-wait-online holds network-online.target (and so
# multi-user.target) until Wi-Fi has an address. Nothing on the box waits
# for that; the app does not use the network at all.
if [ "$(systemctl is-enabled NetworkManager-wait-online 2>/dev/null)" = "enabled" ]; then
    sudo systemctl disable NetworkManager-wait-online >/dev/null 2>&1
    ok "NetworkManager-wait-online disabled"
else
    ok "NetworkManager-wait-online already off"
fi

# Pi OS's NetworkManager keeps its profiles in netplan. At every start it
# rewrites one yaml per profile, and each rewrite runs netplan's generator,
# which ends with a systemd daemon-reload: 6.6 s each on the Zero W, four
# profiles, 44 s. One of those is an Ethernet profile on a board with no
# Ethernet port -- deleted here, on boards without eth0 only.
if [ ! -e /sys/class/net/eth0 ] && nmcli -t -f NAME connection show 2>/dev/null | grep -qx "netplan-eth0"; then
    sudo nmcli connection delete netplan-eth0 >/dev/null 2>&1 \
        && ok "removed the unused Ethernet profile (no eth0 on this board)"
else
    ok "no unused Ethernet profile"
fi

# The user session -- and with it PipeWire and the app -- is gated on
# systemd-user-sessions.service, which upstream orders after network.target
# so that remote logins find the network up. That is the wrong trade here:
# the panel waits a minute for Wi-Fi it will never use. A drop-in cannot
# subtract from After=, so the unit is copied to /etc with network.target
# taken out of its ordering. SSH is unaffected -- sshd has its own ordering
# and users can still log in once it is up. Revisit if a systemd upgrade
# changes the upstream unit; `systemd-delta` shows the override.
USER_SESSIONS_SRC=/usr/lib/systemd/system/systemd-user-sessions.service
USER_SESSIONS_DST=/etc/systemd/system/systemd-user-sessions.service
if [ -f "$USER_SESSIONS_SRC" ]; then
    if [ -f "$USER_SESSIONS_DST" ] && ! grep -q "network.target" "$USER_SESSIONS_DST"; then
        ok "user sessions already decoupled from the network"
    else
        sed -E 's/[[:space:]]*network\.target//' "$USER_SESSIONS_SRC" \
            | sudo tee "$USER_SESSIONS_DST" >/dev/null
        sudo systemctl daemon-reload
        ok "user sessions no longer wait for the network (override in /etc)"
    fi
fi

# Services an appliance does not need, each measured on the Zero W's one
# core. e2scrub_reap reaps LVM snapshots left by online ext4 checks (39 s
# of CPU at boot; there is no LVM here). keyboard-setup configures a console
# keyboard for a box with no keyboard or console. rpi-eeprom-update is for
# boards with a boot EEPROM, which the Zero W is not. The timers are the
# daily apt, man-db and dpkg housekeeping: the device is never online, so
# they would only ever steal the core in the middle of a service.
# fstrim.timer stays -- weekly trim is good for the SD card.
APPLIANCE_OFF=(e2scrub_reap.service keyboard-setup.service e2scrub_all.timer
               apt-daily.timer apt-daily-upgrade.timer man-db.timer
               dpkg-db-backup.timer)
[ "$ARCH" = "armv6l" ] && APPLIANCE_OFF+=(rpi-eeprom-update.service)
TURNED_OFF=()
for unit in "${APPLIANCE_OFF[@]}"; do
    case "$(systemctl is-enabled "$unit" 2>/dev/null)" in
        enabled|static|indirect)
            sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
            sudo systemctl mask "$unit" >/dev/null 2>&1 || true
            TURNED_OFF+=("$unit") ;;
    esac
done
if [ ${#TURNED_OFF[@]} -eq 0 ]; then
    ok "appliance-irrelevant services already off"
else
    ok "turned off: ${TURNED_OFF[*]}"
fi

# One core, and at boot everything wants it at once: NetworkManager,
# wpa_supplicant, netplan's generator and the daemon-reloads it triggers,
# journald -- and the app. Measured on the Zero W after the fixes above: the
# app took 40 s to be ready when contended against 14 s alone. The panel is
# the product and the network is a bench convenience, so the user session
# (the app, PipeWire) gets ten times the CPU weight of system services, and
# the network stack is niced besides. Neither changes anything when the
# core is idle; SSH just comes up a little later while the app is starting.
if [ "$(systemctl show user.slice -p CPUWeight --value)" = "1000" ]; then
    ok "user session already weighted over system services"
else
    sudo systemctl set-property user.slice CPUWeight=1000 >/dev/null 2>&1
    sudo systemctl set-property system.slice CPUWeight=100 >/dev/null 2>&1
    ok "user session weighted 10:1 over system services"
fi
sudo mkdir -p /etc/systemd/system/NetworkManager.service.d \
             /etc/systemd/system/wpa_supplicant.service.d
for svc in NetworkManager wpa_supplicant; do
    sudo tee /etc/systemd/system/$svc.service.d/50-alabanza-nice.conf >/dev/null <<'NICE'
# Alabanza: the panel comes first on a single core -- see provision/README.md
[Service]
Nice=10
NICE
done
sudo systemctl daemon-reload
ok "NetworkManager and wpa_supplicant niced"

# The device is never on the internet (SPEC): Wi-Fi exists so the bench can
# SSH in and push updates, nothing else. On the Zero W even a niced network
# stack costs the app 20 s at boot, so there NetworkManager is taken off the
# boot path entirely and started when the app says it is ready: it touches
# $XDG_RUNTIME_DIR/alabanza.ready (see _mark_ready in app/alabanza/__main__.py)
# and a path unit watches for it. A timer was tried first and fired at a
# guessed 45 s -- into the middle of the app's startup, since the session
# itself does not start at a fixed time. The fallback timer below is only
# for a box where the app never gets to ready: a crash loop must still be
# reachable over SSH.
if [ "$ARCH" = "armv6l" ]; then
    UID_NUM="$(id -u)"
    sudo tee /etc/systemd/system/alabanza-network.service >/dev/null <<'NETUNIT'
# Alabanza: bring the network up after the app -- see provision/README.md
[Unit]
Description=Start the network once the hymn player is up
[Service]
Type=oneshot
# RemainAfterExit: a path unit re-fires for as long as its condition holds
# and its service is not active. Without this the marker (which stays for
# the whole boot) retriggered the start every few seconds until systemd's
# start limit tripped. --no-block: NetworkManager takes a while to become
# active on this board and nothing here needs to wait for it.
RemainAfterExit=yes
ExecStart=/usr/bin/systemctl start --no-block NetworkManager.service
NETUNIT
    sudo tee /etc/systemd/system/alabanza-network.path >/dev/null <<NETPATH
[Unit]
Description=Watch for the hymn player's ready marker
[Path]
PathExists=/run/user/$UID_NUM/alabanza.ready
Unit=alabanza-network.service
[Install]
WantedBy=multi-user.target
NETPATH
    sudo tee /etc/systemd/system/alabanza-network.timer >/dev/null <<'NETTIMER'
[Unit]
Description=Fallback: bring the network up 3 min into boot even if the app never got ready
[Timer]
OnBootSec=180s
AccuracySec=5s
[Install]
WantedBy=timers.target
NETTIMER
    sudo systemctl daemon-reload
    sudo systemctl disable NetworkManager wpa_supplicant >/dev/null 2>&1 || true
    sudo systemctl enable alabanza-network.path alabanza-network.timer >/dev/null 2>&1
    ok "network starts when the app reports ready (alabanza-network.path), or at 3 min"
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

# libopenjp2-7, libjpeg62-turbo, libtiff6, libxcb1, libwebp7
#              What the piwheels Pillow wheel links against at import time.
#              piwheels wheels are built on Pi OS and expect the distro's
#              shared libraries rather than bundling their own, and Lite
#              ships none of the image ones. Without these the venv installs
#              cleanly and the app dies on `import PIL.Image`, which is the
#              first thing the OLED code does.
if [ "$ARCH" = "armv6l" ]; then
    PACKAGES+=(libopenjp2-7 libjpeg62-turbo libtiff6 libxcb1 libwebp7)
fi

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

NEEDED_GROUPS=(gpio i2c audio video input)
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
# Alabanza: prefer the higher-bitpool SBC variant, and a 44.1 kHz link so
# the library is never resampled on the way to the speaker -- see
# provision/README.md.
monitor.bluez.properties = {
  bluez5.enable-sbc-xq = true
  bluez5.codecs = [ sbc_xq sbc aac ]
  bluez5.default.rate = 44100
}
WPCODEC
rm -f "$HOME/.config/wireplumber/wireplumber.conf.d/51-alabanza-test-rate.conf"
ok "Bluetooth codec preference: SBC-XQ before SBC, 44.1 kHz link"

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

# Real-time priority for the audio threads. PipeWire asks rtkit for it, and
# rtkit only grants it to processes in an *active* logind session -- the
# same seat rule that kept WirePlumber's Bluetooth monitor off above. This
# appliance never has one, so every PipeWire data thread ran at ordinary
# priority (ps -eLo rtprio showed '-' for all of them) and took its turn
# behind the app's Python threads. On the Zero W's one core that is the
# difference between a Bluetooth stream that keeps up and one that skips:
# the SBC encoder ran at 85-90% of its cycle with underruns climbing.
# PipeWire's module-rt falls back to setting the priority itself when rtkit
# refuses, provided the user may: that is the limits file and the group.
sudo tee /etc/security/limits.d/95-alabanza-pipewire.conf >/dev/null <<'LIMITS'
# Alabanza: let PipeWire take real-time priority without rtkit (no seat here)
@pipewire   -  rtprio   95
@pipewire   -  nice    -19
@pipewire   -  memlock  4194304
LIMITS
if id -nG "$USER" | tr ' ' '\n' | grep -qx pipewire; then
    ok "$USER is in pipewire (real-time audio allowed)"
else
    sudo groupadd -f pipewire
    sudo usermod -aG pipewire "$USER"
    warn "added $USER to pipewire — takes effect after a reboot"
    ADDED=1
fi

# The graph runs at the library's own rate. The whole library is 44.1 kHz
# AAC, and PipeWire's default graph is a fixed 48 kHz: every sample was
# resampled up on the way in and the Bluetooth node resampled it back down
# to the speaker's 44.1 kHz on the way out, both in software on a core with
# no NEON. Allowing both rates lets the graph follow the stream. The
# quantum is doubled as well: fewer, longer cycles cost less on one core,
# and nothing here needs low latency.
sudo mkdir -p /etc/pipewire/pipewire.conf.d
sudo tee /etc/pipewire/pipewire.conf.d/50-alabanza.conf >/dev/null <<'PWCONF'
# Alabanza: 44.1 kHz library, no resampling, long cycles -- see provision/README.md
context.properties = {
    default.clock.rate          = 44100
    default.clock.allowed-rates = [ 44100 48000 ]
    default.clock.quantum       = 2048
    default.clock.min-quantum   = 1024
    default.clock.max-quantum   = 4096
}
PWCONF
rm -f "$HOME/.config/pipewire/pipewire.conf.d/50-alabanza-test.conf"
ok "PipeWire graph follows the stream rate, 2048-frame quantum"

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

# uv prefers its own managed CPython builds over the system one, and there
# is no managed build for armv6l -- so on the Zero W it must be told to use
# Pi OS's python3 or it stops at "no download available". The venv it makes
# then links against the distro Python, which is also what the piwheels
# Pillow wheel was built for.
if [ "$ARCH" = "armv6l" ]; then
    export UV_PYTHON_PREFERENCE=only-system
    ok "uv pinned to the system python ($(python3 --version))"
fi

cd "$APP"
"$UV" sync --extra test --extra device --quiet
ok "venv ready at app/.venv"

# --- 4b. autostart and shutdown -------------------------------------------

step "Installing the service"

# The app runs as a user service, not a system one. It needs the user's
# PipeWire session for audio, and a system service would have none -- the same
# session that `loginctl enable-linger` above keeps alive without a login.

# The Zero W plays the 480p copy of the library when it has one
# (tools/downscale_library.py, synced with sync.sh --library-480). The
# default library location is unchanged for every other board.
LIBRARY_ARG=""
if [ "$ARCH" = "armv6l" ] && [ -f "$REPO/tools/library-480/manifest.json" ]; then
    LIBRARY_ARG=" --library $REPO/tools/library-480"
    ok "service will play the 480p library"
elif [ "$ARCH" = "armv6l" ]; then
    warn "no tools/library-480/ — the service will play 720p, which the Zero W may not keep up with"
fi
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/alabanza.service" <<UNIT
[Unit]
Description=Alabanza hymn player
After=pipewire.service bluetooth.target
Wants=pipewire.service

[Service]
Type=simple
WorkingDirectory=$APP
ExecStart=$UV run --no-sync --extra device alabanza --gpio --oled-device --bt real$LIBRARY_ARG
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

# Pillow has to import, not merely install. On armv6l it is a piwheels wheel
# that links against distro libraries, and a missing one only shows up here.
if "$UV" run --no-sync python -c "import PIL.Image" 2>/dev/null; then
    ok "Pillow imports"
else
    warn "Pillow does not import — a shared library it needs is missing"
    FAILED=1
fi

# The H.264 block is /dev/video10 (bcm2835-codec). Absent means mpv's
# hwdec=v4l2m2m-copy silently falls back to software, which the Zero W
# and Zero 2 W cannot afford at 720p. Not an error on the bench Pi 4.
if [ -e /dev/video10 ]; then
    ok "hardware video decoder present (/dev/video10)"
else
    warn "no /dev/video10 — hardware H.264 decode unavailable, mpv will use the CPU"
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
