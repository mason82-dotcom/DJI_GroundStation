#!/usr/bin/env bash
# First-time setup of the DJI GroundStation stack.
#   ./scripts/bootstrap.sh [--with-msdk]
# - checks out the pinned submodules (the 300 MB DJI MSDK V5 repo only with --with-msdk,
#   needed for `android-build msdk-sample`)
# - creates .env from .env.example with a random MediaMTX viewer password
# - asks for the web login password (stored only as bcrypt hash)
# - creates the shared data folders
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "Docker fehlt (https://docs.docker.com/engine/install/)" >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 fehlt" >&2; exit 1; }

subs=(upstream/lyrebird upstream/DVM upstream/sdu-agro-tools upstream/crop-row-connector)
[[ "${1:-}" == "--with-msdk" ]] && subs+=(upstream/Mobile-SDK-Android-V5)
git submodule update --init --depth 1 "${subs[@]}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  pass="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
  sed -i "s|^MTX_READ_PASS=.*|MTX_READ_PASS=${pass}|" .env
  echo ".env angelegt."
fi
grep -q '^GS_AUTH_HASH=.\+' .env || ./scripts/gen-password.sh --write

data="$(grep -oP '^GS_DATA_DIR=\K.*' .env || echo ./data)"
mkdir -p "$data"/{media,flightlogs/tlog,orthomosaics,agro-jobs,apk,logs/dashboard}
# QGIS and the Agro API run as uid 1000 and write into the shared folder.
if [[ "$(id -u)" == 0 ]]; then chown -R 1000:1000 "$data"; else chmod -R a+rwX "$data" 2>/dev/null || true; fi

echo
echo "Fertig. Start:  docker compose up -d --build"
echo "Dann im Browser: https://<dieser-rechner>/  (Zertifikat: http://<dieser-rechner>/ca.crt)"
