#!/bin/bash
# Auto-start ClaudeClaw (Telegram bridge) inside the workspace.
#
# Expects /home/coder/claudeclaw/ to contain the bot codebase, with
# package.json + .env in place. If the dist/ build is missing, runs
# `npm run build` first. Daemonizes via tmux so it survives this script
# but stops if the workspace container stops.

set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

CLAUDECLAW_DIR="$HOME/claudeclaw"

if [ ! -d "$CLAUDECLAW_DIR" ]; then
    echo -e "${YELLOW}ClaudeClaw not installed — skipping (clone or copy into ~/claudeclaw to enable)${NC}"
    exit 0
fi

if [ ! -f "$CLAUDECLAW_DIR/.env" ]; then
    echo -e "${YELLOW}ClaudeClaw .env missing — skipping (set TELEGRAM_BOT_TOKEN etc. in ~/claudeclaw/.env)${NC}"
    exit 0
fi

# Already running?
if tmux has-session -t claudeclaw 2>/dev/null; then
    echo -e "${GREEN}ClaudeClaw tmux session already running${NC}"
    exit 0
fi

cd "$CLAUDECLAW_DIR"

# Build if dist/ is missing or older than src/
if [ ! -d dist ] || [ -n "$(find src -newer dist 2>/dev/null | head -1)" ]; then
    echo -e "${BOLD}Building ClaudeClaw (TypeScript -> dist/)${NC}"
    npm install --no-audit --no-fund --silent
    npm run build
fi

echo -e "${BOLD}Starting ClaudeClaw in tmux session 'claudeclaw'${NC}"
tmux new-session -d -s claudeclaw -c "$CLAUDECLAW_DIR" "npm start 2>&1 | tee -a /tmp/claudeclaw.log"

sleep 3
if tmux has-session -t claudeclaw 2>/dev/null; then
    echo -e "${GREEN}ClaudeClaw running. View logs: tail -f /tmp/claudeclaw.log${NC}"
else
    echo -e "${YELLOW}ClaudeClaw failed to start — check /tmp/claudeclaw.log${NC}"
    exit 1
fi
