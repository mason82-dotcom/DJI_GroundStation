#!/usr/bin/env bash
# Print a bcrypt hash for the web login, already escaped for .env ($ -> $$).
#   ./scripts/gen-password.sh            # asks for the password
#   ./scripts/gen-password.sh --write    # asks and stores GS_AUTH_HASH in .env
set -euo pipefail
cd "$(dirname "$0")/.."
read -r -s -p "Web-Login-Passwort: " pw; echo
read -r -s -p "Wiederholen: " pw2; echo
[[ "$pw" == "$pw2" && -n "$pw" ]] || { echo "Passwörter leer oder ungleich" >&2; exit 1; }
hash="$(docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext "$pw")"
escaped="${hash//\$/\$\$}"
if [[ "${1:-}" == "--write" ]]; then
  [[ -f .env ]] || cp .env.example .env
  python3 - "$escaped" <<'PY'
import re, sys
p = ".env"; s = open(p).read(); v = sys.argv[1]
s = re.sub(r"^GS_AUTH_HASH=.*$", lambda m: "GS_AUTH_HASH=" + v, s, flags=re.M) if re.search(r"^GS_AUTH_HASH=", s, re.M) else s + f"\nGS_AUTH_HASH={v}\n"
open(p, "w").write(s)
PY
  echo "GS_AUTH_HASH in .env gesetzt."
else
  echo "GS_AUTH_HASH=$escaped"
fi
