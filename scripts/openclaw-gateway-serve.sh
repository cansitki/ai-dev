#!/bin/bash
set -euo pipefail

export OPENCLAW_PREFIX="${OPENCLAW_PREFIX:-$HOME/.openclaw}"
export PATH="$HOME/.local/bin:$OPENCLAW_PREFIX/bin:$PATH"

mkdir -p "$OPENCLAW_PREFIX/logs" "$OPENCLAW_PREFIX/workspace"

if [ -f "$OPENCLAW_PREFIX/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$OPENCLAW_PREFIX/.env"
  set +a
fi
if [ -f "$OPENCLAW_PREFIX/gateway.env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$OPENCLAW_PREFIX/gateway.env"
  set +a
fi

if ! command -v openclaw >/dev/null 2>&1; then
  echo "OpenClaw is not installed yet."
  exit 0
fi

if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
  echo "OPENCLAW_GATEWAY_TOKEN is not set in $OPENCLAW_PREFIX/gateway.env; leaving gateway stopped."
  exit 0
fi

if tmux has-session -t openclaw-gateway 2>/dev/null; then
  echo "openclaw-gateway tmux session already running."
  exit 0
fi

tmux new-session -d -s openclaw-gateway -c "$OPENCLAW_PREFIX/workspace" \
  "openclaw gateway run --port 18789 --bind lan --auth token=\"\$OPENCLAW_GATEWAY_TOKEN\" 2>&1 | tee -a \"$OPENCLAW_PREFIX/logs/gateway.tmux.log\""

echo "OpenClaw gateway started in tmux session openclaw-gateway."
