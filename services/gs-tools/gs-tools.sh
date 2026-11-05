#!/usr/bin/env bash
# gs-tools: Lyrebird ground-station CLI tools in one container (host network).
#   docker compose run --rm gs-tools <command> [args...]
# The scripts run straight from the pinned submodule (mounted read-only at /opt/lyrebird-gs).
set -euo pipefail
GS=/opt/lyrebird-gs
cmd="${1:-help}"; shift || true

case "$cmd" in
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
