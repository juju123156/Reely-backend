#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/home-macbook/docker-compose.yml"

cd "$ROOT"
docker compose -f "$COMPOSE_FILE" down

