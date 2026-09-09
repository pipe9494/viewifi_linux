#!/usr/bin/env bash
# Viewifi Linux host installer — Raspberry Pi OS / Debian / Ubuntu.
# Run:  curl -sSL https://raw.githubusercontent.com/pipe9494/viewifi_linux/main/install.sh | sudo bash
#   or: git clone https://github.com/pipe9494/viewifi_linux.git && cd viewifi_linux && sudo ./install.sh
set -euo pipefail

INSTALL_DIR=/opt/viewifi
SERVICE=viewifi-host

echo "==> Installing system packages (iw, python3, optional evidence tools)"
apt-get update -qq
apt-get install -y -qq python3 iw wireless-tools
# Optional evidence capture (photo/audio) — ignored if no camera/mic present
apt-get install -y -qq fswebcam alsa-utils ffmpeg || true

if [ ! -d "$INSTALL_DIR" ]; then
  echo "==> Installing Viewifi to $INSTALL_DIR"
  if [ -d "$(dirname "$0")/viewifi" ]; then
    # installing from a local clone
    mkdir -p "$INSTALL_DIR"
    cp -r "$(dirname "$0")/viewifi" "$INSTALL_DIR/"
  else
    git clone --depth 1 https://github.com/pipe9494/viewifi_linux.git /tmp/viewifi_linux
    mkdir -p "$INSTALL_DIR"
    cp -r /tmp/viewifi_linux/viewifi "$INSTALL_DIR/"
  fi
fi

RUN_USER="${SUDO_USER:-$USER}"

echo "==> Installing systemd service (user: $RUN_USER)"
cp "$(dirname "$0")/systemd/${SERVICE}@.service" /etc/systemd/system/ 2>/dev/null \
  || cp /tmp/viewifi_linux/systemd/${SERVICE}@.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "${SERVICE}@${RUN_USER}"

echo ""
echo "==> Done. Next steps:"
echo "  1) Configure:            cd $INSTALL_DIR && python3 -m viewifi.main --setup"
echo "     (as user '$RUN_USER'; config lives in ~/.viewifi/config.json)"
echo "  2) Start monitoring:     sudo systemctl start ${SERVICE}@${RUN_USER}"
echo "  3) Follow the log:       journalctl -fu ${SERVICE}@${RUN_USER}"
echo ""
echo "The service restarts automatically on crash and starts on boot."
