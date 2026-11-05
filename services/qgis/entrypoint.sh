#!/usr/bin/env bash
# QGIS web desktop: Xvfb + openbox + x11vnc (loopback) + noVNC/websockify (container port).
# Authentication is Caddy's job; the container port is only published on the host's loopback.
set -euo pipefail

PROFILE_DIR="${HOME}/.local/share/QGIS/QGIS3/profiles/default"
SKEL_PROFILE="/opt/qgis-skel/.local/share/QGIS/QGIS3/profiles/default"
NOVNC_PORT="${NOVNC_PORT:-6080}"
mkdir -p "${XDG_RUNTIME_DIR}" && chmod 700 "${XDG_RUNTIME_DIR}"

# First start: seed the persistent profile. Later starts: refresh only the plugin code, so an
# image update ships the pinned plugin revision without wiping the user's QGIS settings.
if [[ ! -d "${PROFILE_DIR}" ]]; then
  mkdir -p "$(dirname "${PROFILE_DIR}")"
  cp -a "${SKEL_PROFILE}" "${PROFILE_DIR}"
  echo "[qgis] seeded QGIS profile"
fi
mkdir -p "${PROFILE_DIR}/python/plugins"
rm -rf "${PROFILE_DIR}/python/plugins/SDU_Agro_Tools"
cp -a "${SKEL_PROFILE}/python/plugins/SDU_Agro_Tools" "${PROFILE_DIR}/python/plugins/"

Xvfb "${DISPLAY}" -screen 0 "${VNC_GEOMETRY}x24" -nolisten tcp &
for _ in $(seq 1 50); do xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1 && break; sleep 0.2; done
openbox >/dev/null 2>&1 &
x11vnc -display "${DISPLAY}" -localhost -forever -shared -nopw -quiet -rfbport 5900 &
websockify --web /usr/share/novnc "0.0.0.0:${NOVNC_PORT}" 127.0.0.1:5900 &

echo "[qgis] noVNC ready on :${NOVNC_PORT}/vnc.html (proxied by Caddy)"
# Keep QGIS running: if the user closes it, start it again instead of leaving a blank desktop.
while true; do
  qgis --nologo || true
  echo "[qgis] QGIS exited, restarting in 2 s"
  sleep 2
done
