#!/usr/bin/env bash
# QGroundControl web desktop: Xvfb + openbox + x11vnc (loopback) + noVNC/websockify (loopback, host network).
# Authentication and TLS are Caddy's job; nothing here listens on a LAN address.
set -euo pipefail

NOVNC_PORT="${NOVNC_PORT:-16081}"
VNC_PORT="${VNC_PORT:-5902}"
mkdir -p "${XDG_RUNTIME_DIR}" && chmod 700 "${XDG_RUNTIME_DIR}"

# Router link, no UDP auto-connect (mavlink-router owns UDP 14550), GCS system ID, heartbeat on.
gs-qgc-seed --host 127.0.0.1 --port "${MAVLINK_TCP_PORT:-5760}" --system-id "${QGC_SYSTEM_ID:-254}"

Xvfb "${DISPLAY}" -screen 0 "${VNC_GEOMETRY}x24" -nolisten tcp &
for _ in $(seq 1 50); do xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 && break; sleep 0.2; done
openbox --config-file /etc/gs-qgc/openbox-rc.xml >/dev/null 2>&1 &
x11vnc -display "${DISPLAY}" -localhost -forever -shared -nopw -quiet -rfbport "${VNC_PORT}" &
websockify --web /usr/share/novnc "127.0.0.1:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" &

echo "[qgc] noVNC ready on 127.0.0.1:${NOVNC_PORT}/vnc.html (proxied by Caddy)"
# Keep QGC running: if the user closes it, start it again instead of leaving a blank desktop.
while true; do
  /opt/qgc/AppRun || true
  echo "[qgc] QGroundControl exited, restarting in 2 s"
  sleep 2
done
