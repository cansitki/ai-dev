#!/bin/bash
# Run ttyd inside the workspace, serving an interactive tmux session
# picker at http://localhost:7681. Coder exposes this via the
# `tmux_picker` coder_app on the dashboard.

set -e

PORT=7681
PICKER="${HOME}/.local/bin/tmux-picker"

mkdir -p "${HOME}/.local/bin"

# Install picker script if missing or older than the template copy
TEMPLATE_PICKER="$(dirname "$0")/tmux-picker"
if [ -f "$TEMPLATE_PICKER" ]; then
  cp "$TEMPLATE_PICKER" "$PICKER"
  chmod +x "$PICKER"
fi

if [ ! -x "$PICKER" ]; then
  echo "ERROR: tmux picker not found at $PICKER" >&2
  exit 1
fi

# Kill any existing ttyd on this port
pkill -f "ttyd -p ${PORT}" 2>/dev/null || true

# Run ttyd inside a tmux session so it survives the script exit
tmux kill-session -t ttyd 2>/dev/null || true
tmux new-session -d -s ttyd \
  "ttyd -p ${PORT} -W -t titleFixed='Workspace Tmux' ${PICKER}"

echo "ttyd serving tmux picker on :${PORT}"
