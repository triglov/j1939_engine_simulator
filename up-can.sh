#!/usr/bin/env bash
# Podnosi interfejs CAN w WSL (250 kbit/s dla J1939).
#   ./up-can.sh                 -> can0, natywny SocketCAN (gs_usb/candleLight)
#   ./up-can.sh can0 slcan [/dev/ttyACM0]  -> adapter slcan (port szeregowy)
#   ./up-can.sh vcan0           -> wirtualny interfejs do testów
#   ./up-can.sh down [can0]     -> wyłącz
set -euo pipefail
IF="${1:-can0}"; MODE="${2:-native}"; TTY="${3:-/dev/ttyACM0}"; BITRATE="${BITRATE:-250000}"
need() { command -v "$1" >/dev/null || { echo "Brak '$1' (sudo apt install ${2:-$1})"; exit 1; }; }
mod() { sudo modprobe "$1" 2>/dev/null || { echo "!! modprobe $1 nie działa – kernel WSL nie ma tego modułu (uname -r: $(uname -r)). Zaktualizuj: 'wsl --update' (kernel 6.18+) – patrz README."; return 1; }; }
need ip iproute2

if [ "$IF" = "down" ]; then
  T="${2:-can0}"; sudo ip link set "$T" down || true
  [[ "$T" == vcan* ]] && sudo ip link del "$T" || true
  pkill -f "slcand.*$T" 2>/dev/null || true; exit 0
fi

mod can_raw || true
if [[ "$IF" == vcan* ]]; then
  mod vcan
  ip link show "$IF" >/dev/null 2>&1 || sudo ip link add dev "$IF" type vcan
  sudo ip link set up "$IF"
elif [ "$MODE" = "slcan" ]; then
  need slcand can-utils
  mod slcan
  case "$BITRATE" in 10000) S=0;; 20000) S=1;; 50000) S=2;; 100000) S=3;; 125000) S=4;; 250000) S=5;; 500000) S=6;; 800000) S=7;; 1000000) S=8;; *) echo "zły BITRATE"; exit 1;; esac
  [ -e "$TTY" ] || { echo "Brak $TTY (lsusb / ls /dev/ttyACM* /dev/ttyUSB*)"; exit 1; }
  sudo slcand -o -c -s"$S" "$TTY" "$IF"
  sleep 1
  sudo ip link set up "$IF"
else
  mod gs_usb || true
  ip link show "$IF" >/dev/null 2>&1 || { echo "Brak $IF. Czy adapter jest podpięty do WSL (usbipd attach) i czy to gs_usb? Spróbuj: ./up-can.sh $IF slcan"; exit 1; }
  sudo ip link set "$IF" down 2>/dev/null || true
  sudo ip link set "$IF" type can bitrate "$BITRATE" restart-ms 100
  sudo ip link set up "$IF"
fi
ip -details link show "$IF" | sed -n '1,4p'
echo "OK: $IF up. Podgląd: candump -td $IF"
