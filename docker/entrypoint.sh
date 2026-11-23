#!/bin/sh
# Seeds /data/flows.json from the baked flow on first start (or always with FLOW_RESET=1), then starts Node-RED.
set -e
cd /usr/src/node-red
# marker file: base image ships a placeholder /data/flows.json, so don't rely on "file exists"
if [ ! -f /data/.vp-flow-seeded ] || [ "$FLOW_RESET" = "1" ]; then
  rm -f /data/flows.json
  cp /usr/src/node-red/vp-flow.json /data/flows.json
  touch /data/.vp-flow-seeded
  echo "[vp-sim] /data/flows.json zaladowany z obrazu (FLOW_RESET=${FLOW_RESET})"
fi
echo "[vp-sim] CAN_IF=${CAN_IF}  VP_START_HOURS=${VP_START_HOURS}"
if ! ip link show "${CAN_IF}" >/dev/null 2>&1; then
  echo "[vp-sim] UWAGA: brak interfejsu ${CAN_IF} w tej przestrzeni sieciowej (uruchom ./up-can.sh na hoscie WSL; network_mode: host)"
fi
exec node $NODE_OPTIONS node_modules/node-red/red.js --userDir /data --settings /usr/src/node-red/vp-settings.js flows.json
