#!/bin/bash
# Run from the host. Installs/re-installs everything the board must have for
# the R5F/ChibiOS ArduCopter build to work, in one idempotent shot, so a
# reflash of the board cannot silently drop pieces the way it has before
# (2026-09-07 lost three of them; 2026-09-08 found gem-storaged had never been
# installed at all, which is why no calibration ever survived a reboot):
#
#   chibios-spi-release   - frees SPI0 from Linux so the R5F can reach the
#                           IMU/baro
#   chibios-uart6-release - frees MAIN_UART6 (2860000.serial) from Linux's
#                           omap8250 so the R5F can reach the GPS. Linux
#                           re-binds it from the device tree on every boot,
#                           hence a service and not a one-off command
#   chibios-pwm-clocks    - turns on the motor PWM clocks (without this,
#                           arming looks fine but motors never spin)
#   gem-storaged          - persists R5F parameter/calibration writes to
#                           /home/gemstone/gem_storage.bin; without it every
#                           setting/calibration is silently lost on reboot
#   gem_mavbridge.py      - board half of the MAVLink bridge, launched over
#                           ssh by the host's run_bridge.py (it lives under
#                           deploy/host/ despite running on the board)
#
# Safe to re-run any time (systemctl enable --now is idempotent, and the
# .service/.py files are just overwritten with the current repo copies).
set -euo pipefail

BOARD_HOST="gemstone@192.168.7.2"
BOARD_PASS="gem"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ssh_board() {
    sshpass -p "$BOARD_PASS" ssh -o StrictHostKeyChecking=no "$BOARD_HOST" "$@"
}

scp_board() {
    sshpass -p "$BOARD_PASS" scp -o StrictHostKeyChecking=no "$@"
}

echo "[install-board] copying files to the board..."
scp_board \
    "$SCRIPT_DIR/systemd-board/chibios-spi-release.service" \
    "$SCRIPT_DIR/systemd-board/chibios-uart6-release.service" \
    "$SCRIPT_DIR/systemd-board/chibios-pwm-clocks.service" \
    "$SCRIPT_DIR/systemd-board/gem-storaged.service" \
    "$SCRIPT_DIR/board/gem_storaged.py" \
    "$SCRIPT_DIR/host/gem_mavbridge.py" \
    "$BOARD_HOST:/tmp/"

echo "[install-board] installing on the board..."
ssh_board "echo $BOARD_PASS | sudo -S bash -s" <<'REMOTE'
set -euo pipefail
cp /tmp/chibios-spi-release.service   /etc/systemd/system/chibios-spi-release.service
cp /tmp/chibios-uart6-release.service /etc/systemd/system/chibios-uart6-release.service
cp /tmp/chibios-pwm-clocks.service  /etc/systemd/system/chibios-pwm-clocks.service
cp /tmp/gem-storaged.service        /etc/systemd/system/gem-storaged.service
cp /tmp/gem_storaged.py             /home/gemstone/gem_storaged.py
cp /tmp/gem_mavbridge.py            /home/gemstone/gem_mavbridge.py

systemctl daemon-reload
systemctl enable --now chibios-spi-release chibios-uart6-release chibios-pwm-clocks gem-storaged

# The legacy Linux-side ArduCopter fights the R5F for SPI0 and UDP 14550 if it
# is ever left enabled -- it was, and it did (2026-09-07).
systemctl disable --now arducopter 2>/dev/null || true
REMOTE

echo "[install-board] verifying..."
ssh_board "systemctl is-active chibios-spi-release chibios-uart6-release chibios-pwm-clocks gem-storaged"

echo "[install-board] done."
echo
echo "For the R5F to pick these up (or any new firmware), a soft reboot is NOT"
echo "enough, and neither is a brief power cut: the MCU domain stays alive on"
echo "USB-C VBUS and keeps running the old image straight through both."
echo "Unplug BOTH the power and the USB-C cable, wait ~20s, then reconnect."
echo "Confirm it really reset -- trace0 must start with a fresh"
echo "  AP-K3: run() entry, build <today's date>"
echo "and any counter in it (e.g. 'begin #N') must restart from 1."
