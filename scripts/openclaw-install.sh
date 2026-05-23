#!/bin/bash
set -euo pipefail

BOLD='\033[0;1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

export OPENCLAW_PREFIX="${OPENCLAW_PREFIX:-$HOME/.openclaw}"
export PATH="$HOME/.local/bin:$OPENCLAW_PREFIX/bin:$PATH"

mkdir -p "$HOME/.local/bin" "$OPENCLAW_PREFIX/workspace" "$OPENCLAW_PREFIX/logs" "$OPENCLAW_PREFIX/credentials"

if ! command -v openclaw >/dev/null 2>&1; then
  printf "${BOLD}[install] OpenClaw local prefix at %s...${RESET}\n" "$OPENCLAW_PREFIX"
  curl -fsSL https://openclaw.ai/install-cli.sh | bash
fi

if [ -x "$OPENCLAW_PREFIX/bin/openclaw" ]; then
  ln -sf "$OPENCLAW_PREFIX/bin/openclaw" "$HOME/.local/bin/openclaw"
elif command -v openclaw >/dev/null 2>&1; then
  ln -sf "$(command -v openclaw)" "$HOME/.local/bin/openclaw"
fi

if [ -f "$HOME/vault/AGENTS.md" ]; then
  ln -sf "$HOME/vault/AGENTS.md" "$OPENCLAW_PREFIX/workspace/AGENTS.md"
elif [ -f "$HOME/vault/CLAUDE.md" ]; then
  ln -sf "$HOME/vault/CLAUDE.md" "$OPENCLAW_PREFIX/workspace/AGENTS.md"
fi

if [ ! -f "$OPENCLAW_PREFIX/gateway.env" ]; then
  cat > "$OPENCLAW_PREFIX/gateway.env" <<'EOF'
# Fill after workspace creation.
# OPENCLAW_GATEWAY_TOKEN=
EOF
  chmod 600 "$OPENCLAW_PREFIX/gateway.env"
fi

if command -v openclaw >/dev/null 2>&1; then
  printf "${GREEN}[ok] OpenClaw installed: %s${RESET}\n" "$(command -v openclaw)"
  openclaw --version || true
else
  printf "${YELLOW}[warn] OpenClaw installer completed but openclaw is not on PATH${RESET}\n"
fi
