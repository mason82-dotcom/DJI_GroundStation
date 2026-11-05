#!/usr/bin/env bash
# gs-tools: Lyrebird ground-station CLI tools in one container (host network).
#   docker compose run --rm gs-tools <command> [args...]
# The scripts run straight from the pinned submodule (mounted read-only at /opt/lyrebird-gs).
set -euo pipefail
GS="${GS_LYREBIRD:-/opt/lyrebird-gs}"
DATA="${GS_DATA:-/data}"
cmd="${1:-help}"; shift || true

# Field-test phases in the order of the Lyrebird field-test guide (docs/feldtest.md), each one
# logged to /data/fieldtest/<date>/<time>-<phase>-<ip>.log so the run is reviewable afterwards.
fieldtest() {
  local phase="${1:?usage: fieldtest <link|ground|payload|ftp|signing|flight> PHONE_IP [args]}"
  local ip="${2:?usage: fieldtest $phase PHONE_IP [args]}"; shift 2
  local -a run
  case "$phase" in
    link)    run=(python "$GS/Python/test_scripts/field_check.py" "$ip") ;;
    ground)  run=(python "$GS/Python/test_scripts/field_check.py" "$ip" --phase ground) ;;
    payload) run=(python "$GS/Python/test_scripts/field_check.py" "$ip" --phase payload --move) ;;
    ftp)     run=(python "$GS/Python/test_scripts/ftp_exercise.py" "$ip") ;;
    signing) run=(python "$GS/Python/test_scripts/signing_exercise.py" "$ip") ;;
    flight)  run=(python "$GS/Python/test_scripts/field_check.py" "$ip" --phase flight --fly) ;;
    *) echo "unknown phase: $phase" >&2; return 2 ;;
  esac
  local dir="$DATA/fieldtest/$(date +%F)"; mkdir -p "$dir"
  local log="$dir/$(date +%H%M%S)-${phase}-${ip//[^0-9A-Za-z.]/_}.log"
  echo "# fieldtest $phase $ip $* -- $(date -Is) -- LB_MAVLINK_PORT=${LB_MAVLINK_PORT:-14550}" > "$log"
  set +e
  "${run[@]}" "$@" 2>&1 | tee -a "$log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "# exit $rc" >> "$log"
  echo "Protokoll: ${log#"$DATA"/} (Archiv-Browser, Port 9443)"
  return "$rc"
}

case "$cmd" in
  fieldtest)     fieldtest "$@"; exit $? ;;
  discover)      exec python -c 'from lyrebird_groundstation.discovery import discover_all
for d in discover_all(timeout=3.0, verbose=False, per_interface_broadcast=True): print(f"{d.name}\t{d.ip_address}")' ;;
  mavlink-listen) exec lyrebird-mavlink-listen "$@" ;;
  field-check)   exec python "$GS/Python/test_scripts/field_check.py" "$@" ;;
  signing)       exec python "$GS/Python/test_scripts/signing_exercise.py" "$@" ;;
  authority)     exec python "$GS/Python/test_scripts/test_authority.py" "$@" ;;
  ftp)           exec python "$GS/Python/test_scripts/ftp_exercise.py" "$@" ;;
  capture)       exec python "$GS/Python/test_scripts/test_capture_download.py" "$@" ;;
  example)
    name="${1:?usage: example <http_raw|python_client|mavlink_pymavlink> [args]}"; shift
    exec python "$GS/examples/${name%.py}.py" "$@" ;;
  python|bash|sh) exec "$cmd" "$@" ;;
  help|*)
    cat <<'HELP'
gs-tools -- Lyrebird ground-station tools (upstream/lyrebird/GroundStation)

  fieldtest PHASE PHONE_IP         staged field test, logged to data/fieldtest/<date>/:
                                   link | ground | payload | ftp | signing | flight
                                   (order and meaning: docs/feldtest.md)
  discover                         find Lyrebird aircraft on the LAN (UDP broadcast)
  mavlink-listen [--summary 5]     print the MAVLink stream (read-only; UDP 14550 must be free,
                                   e.g. --port 14553 while mavlink-router is running)
  field-check PHONE_IP [--phase ground|payload|flight] [--move] [--fly]
                                   staged field test from the Lyrebird field-test guide
  signing PHONE_IP [KEY_HEX]       exercise MAVLink 2 signing / Safety-Computer authority
  authority ...                    HTTP two-computer safety authority test
  ftp PHONE_IP                     MAVLink FTP listing/download exercise
  capture PHONE_IP                 capture + download a photo
  example NAME [args]              flight examples: http_raw, python_client, mavlink_pymavlink
                                   (all support a dry run -- read GroundStation/examples/README.md)
  python | bash                    shell with the lyrebird_groundstation client installed

Downloads land in the current directory; use --out /data/... (or cd /data) to keep them.
HELP
    [[ "$cmd" == help ]] || exit 2 ;;
esac
