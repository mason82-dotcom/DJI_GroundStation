#!/usr/bin/env bash
# QGroundControl web desktop: Xvfb + openbox + x11vnc (loopback) + noVNC/websockify (loopback, host network).
# Authentication and TLS are Caddy's job; nothing here listens on a LAN address.
# The X display needs its own cookie: in the host network its abstract socket (@/tmp/.X11-unix/X2) is reachable by
# every process on the machine, which could otherwise send input to QGC past the Caddy login.
set -euo pipefail

NOVNC_PORT="${NOVNC_PORT:-16081}"
VNC_PORT="${VNC_PORT:-5902}"
mkdir -p "${XDG_RUNTIME_DIR}" && chmod 700 "${XDG_RUNTIME_DIR}"

# Router link, no UDP auto-connect (mavlink-router owns UDP 14550), GCS system ID, heartbeat on.
seed() {
  gs-qgc-seed --host 127.0.0.1 --port "${MAVLINK_TCP_PORT:-5760}" --system-id "${QGC_SYSTEM_ID:-254}" \
    --settings-version "${QGC_SETTINGS_VERSION:-9}" --save-path "${QGC_SAVE_PATH:-/data/qgc}"
}
mkdir -p "${QGC_SAVE_PATH:-/data/qgc}"

# A container restart keeps /tmp, so the lock of the previous Xvfb would make the new one refuse the display
# and leave the app restarting against a dead display (seen on brix 07.11.2026). Nothing in this fresh PID
# namespace owns the display yet: remove the stale lock and socket, then fail loudly if Xvfb still does not come up.
n="${DISPLAY#:}"; n="${n%%.*}"
rm -f "/tmp/.X${n}-lock" "/tmp/.X11-unix/X${n}"
rm -f "${XAUTHORITY}" && touch "${XAUTHORITY}" && chmod 600 "${XAUTHORITY}"
xauth -f "${XAUTHORITY}" add "${DISPLAY}" . "$(mcookie)"
Xvfb "${DISPLAY}" -screen 0 "${VNC_GEOMETRY}x24" -nolisten tcp -auth "${XAUTHORITY}" &
for _ in $(seq 1 50); do xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 && break; sleep 0.2; done
xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 || { echo "[qgc] Xvfb did not start on ${DISPLAY}" >&2; exit 1; }
openbox --config-file /etc/gs-qgc/openbox-rc.xml >/dev/null 2>&1 &
x11vnc -display "${DISPLAY}" -auth "${XAUTHORITY}" -localhost -forever -shared -nopw -quiet -rfbport "${VNC_PORT}" &
websockify --web /usr/share/novnc "127.0.0.1:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" &

echo "[qgc] noVNC ready on 127.0.0.1:${NOVNC_PORT}/vnc.html (proxied by Caddy)"
# Keep QGC running: if the user closes it, start it again instead of leaving a blank desktop.
while true; do
  seed  # before every start: a wipe by QGC (or a closed session) never leaves UDP 14550 auto-connect behind
  /opt/qgc/AppRun || true
  echo "[qgc] QGroundControl exited, restarting in 2 s"
  sleep 2
done
