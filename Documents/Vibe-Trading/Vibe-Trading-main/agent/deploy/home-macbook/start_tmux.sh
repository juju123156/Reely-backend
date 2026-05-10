#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/home-macbook/docker-compose.yml"
SESSION="${VIBE_TMUX_SESSION:-vibe-trading}"

cd "$ROOT"

command -v docker >/dev/null || { echo "docker not found"; exit 1; }
command -v tmux >/dev/null || { echo "tmux not found"; exit 1; }

if [ ! -f "$ROOT/.env.paper" ]; then
  echo "missing .env.paper"
  exit 1
fi

mkdir -p "$ROOT/data"
touch "$ROOT/paper_trading.log"

docker compose -f "$COMPOSE_FILE" up -d --build

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux attach -t "$SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" -c "$ROOT" "docker compose -f '$COMPOSE_FILE' logs -f --tail=160 bot"
tmux rename-window -t "$SESSION:0" "bot-log"

tmux new-window -t "$SESSION" -n "dashboard-log" -c "$ROOT" "docker compose -f '$COMPOSE_FILE' logs -f --tail=120 dashboard"
tmux new-window -t "$SESSION" -n "status" -c "$ROOT" "watch -n 5 \"docker compose -f '$COMPOSE_FILE' ps && echo && tail -30 paper_trading.log\""
tmux new-window -t "$SESSION" -n "shell" -c "$ROOT"

tmux select-window -t "$SESSION:status"
tmux attach -t "$SESSION"

