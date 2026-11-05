#!/usr/bin/env bash
# Local quality gate (also run by CI): compose config, shell syntax, Python tests and lint.
set -euo pipefail
cd "$(dirname "$0")/.."
export GS_AUTH_HASH="${GS_AUTH_HASH:-dummy}"
for p in "" archive ros dvm agro odm qgc tools android; do
  COMPOSE_PROFILES="$p" docker compose --env-file .env.example config --quiet
done
echo "compose: ok"
bash -n scripts/*.sh services/*/*.sh
echo "shell: ok"
(cd services/agro-api && uv run --locked --group test --group lint ruff check . && uv run --locked --group test --group lint ruff format --check . && uv run --locked --group test --group tools pytest -q)
uv run --with pytest --no-project pytest -q services/media-sync/tests services/gs-init/tests services/qgc/tests scripts/tests
