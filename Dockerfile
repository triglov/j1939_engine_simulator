# Volvo Penta J1939 simulator: Node-RED 4 + Dashboard 2 + SocketCAN
# Build:  docker compose build      Run: docker compose up -d   (see README, section Docker)
ARG NODE_RED_IMAGE=nodered/node-red:4.1.17-22

# ---- builder: compile the native socketcan addon (musl/Alpine, same base as runtime) ----
FROM ${NODE_RED_IMAGE} AS build
USER root
RUN apk add --no-cache build-base python3 linux-headers
WORKDIR /usr/src/node-red
USER node-red
RUN npm --version && npm install --no-fund --no-audit --no-update-notifier --omit=dev \
        node-red-contrib-socketcan@1.4.2 @flowfuse/node-red-dashboard@1.34.1 \
 # npm 11+ may skip dependency install scripts (allowScripts) -> build the addon explicitly with node-gyp
 && (cd node_modules/socketcan && npx --yes node-gyp@11 rebuild) \
 && node -e "require('socketcan'); console.log('socketcan native addon OK')"

# ---- runtime ----
FROM ${NODE_RED_IMAGE}
# drop the base image placeholder flow (it would mask ours)
USER root
RUN rm -f /data/flows.json
USER node-red
COPY --from=build --chown=node-red:node-red /usr/src/node-red/node_modules /usr/src/node-red/node_modules
COPY --from=build --chown=node-red:node-red /usr/src/node-red/package.json /usr/src/node-red/package-lock.json /usr/src/node-red/
COPY --chown=node-red:node-red docker/settings.js /usr/src/node-red/vp-settings.js
COPY --chown=node-red:node-red docker/entrypoint.sh /usr/src/node-red/vp-entrypoint.sh
COPY --chown=node-red:node-red flow.json /usr/src/node-red/vp-flow.json
ENV CAN_IF=can0 \
    VP_START_HOURS=1234.5 \
    FLOW_RESET=0 \
    TZ=Europe/Warsaw
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD wget -q -O /dev/null http://127.0.0.1:1880/dashboard/ || exit 1
ENTRYPOINT ["/bin/sh", "/usr/src/node-red/vp-entrypoint.sh"]
