#!/bin/bash
# Auto-start the discord bot inside the Coder workspace.
#
# Idempotent: skips if the tmux session is already running.
# Self-restarting: wraps the bot in a `while true; do ... ; done` loop
# so it comes back if it crashes. The loop only stops when the
# workspace container stops.
#
# Invoked by the Coder workspace's `coder_script` on start, but can
# also be run manually from a shell.

set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

BOT_DIR="$HOME/projects/discord-bot"
# 'bot' rather than 'discord-bot' so the name doesn't clash with the
# Claude Code tmux session people often run for this project.
SESSION="bot"

if [ ! -d "$BOT_DIR" ]; then
    echo -e "${YELLOW}discord-bot not installed at $BOT_DIR — skipping${NC}"
    exit 0
fi

if [ ! -f "$BOT_DIR/.env" ] && [ -f "$BOT_DIR/.env.example" ]; then
    cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
    chmod 600 "$BOT_DIR/.env"
    echo -e "${YELLOW}Created $BOT_DIR/.env from .env.example. Fill tokens before the bot can start.${NC}"
fi

if [ ! -f "$BOT_DIR/.env" ]; then
    echo -e "${YELLOW}discord-bot .env missing — skipping${NC}"
    exit 0
fi

if [ ! -x "$BOT_DIR/.venv/bin/python" ]; then
    echo -e "${BOLD}Building discord-bot virtualenv${NC}"
    python3 -m venv "$BOT_DIR/.venv"
    "$BOT_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
    "$BOT_DIR/.venv/bin/python" -m pip install -e "$BOT_DIR"
fi

if ! grep -Eq '^DISCORD_BOT_TOKEN=.+$' "$BOT_DIR/.env"; then
    echo -e "${YELLOW}discord-bot token not configured in $BOT_DIR/.env — skipping start${NC}"
    exit 0
fi

# Already running?
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo -e "${GREEN}discord-bot tmux session already running${NC}"
    exit 0
fi

mkdir -p "$BOT_DIR/logs"

echo -e "${BOLD}Starting discord-bot in tmux session '$SESSION'${NC}"
# The inner shell loops so a crash auto-restarts after 5s.
tmux new-session -d -s "$SESSION" -c "$BOT_DIR" \
    'while true; do .venv/bin/python -m bot 2>&1 | tee -a logs/bot.log; echo "[$(date)] bot exited code $? — restarting in 5s" | tee -a logs/bot.log; sleep 5; done'

sleep 4
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo -e "${GREEN}discord-bot running. Logs: tail -f $BOT_DIR/logs/bot.log${NC}"
else
    echo -e "${RED}discord-bot failed to start — check $BOT_DIR/logs/bot.log${NC}"
    exit 1
fi
