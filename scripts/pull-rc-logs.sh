#!/usr/bin/env bash
# Copy the logs that Lyrebird keeps ON THE RC / phone into the archive, over USB (adb).
# The app does not serve these over the network, so this complements media-sync's ground-side
# telemetry logs. Locations from the Lyrebird operations guide:
#   SD card:   Lyrebird/FlightLogs/YYYY-MM-DD/*.jsonl   and   Lyrebird/DJI_FlightRecords/
#   fallback:  Documents/lyrebird/FlightLogs/
#   ./scripts/pull-rc-logs.sh [adb-serial]
set -euo pipefail
cd "$(dirname "$0")/.."
command -v adb >/dev/null || { echo "adb fehlt (Android platform-tools)" >&2; exit 1; }
serial="${1:-}"; adb_cmd=(adb); [[ -n "$serial" ]] && adb_cmd+=(-s "$serial")
dev="$("${adb_cmd[@]}" get-serialno)"
data="$(grep -oP '^GS_DATA_DIR=\K.*' .env 2>/dev/null || echo ./data)"
target="$data/flightlogs/rc/$dev"; mkdir -p "$target"
for base in $("${adb_cmd[@]}" shell 'ls -d /storage/*/Lyrebird /sdcard/Lyrebird /sdcard/Documents/lyrebird 2>/dev/null' | tr -d '\r'); do
  for sub in FlightLogs DJI_FlightRecords; do
    if "${adb_cmd[@]}" shell "[ -d '$base/$sub' ]" ; then
      echo "pull $base/$sub"; "${adb_cmd[@]}" pull "$base/$sub" "$target/" >/dev/null
    fi
  done
done
echo "Logs von $dev liegen in $target"
