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
  cat >"$PICKER" <<'PICKER_EOF'
#!/usr/bin/env bash
set -euo pipefail

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed."
  exec bash -l
fi

while true; do
  clear
  echo "Workspace tmux sessions"
  echo
  mapfile -t sessions < <(tmux list-sessions -F '#S' 2>/dev/null || true)
  if [ "${#sessions[@]}" -eq 0 ]; then
    echo "No tmux sessions exist yet."
    echo "Press Enter to open a shell."
    read -r _
    exec bash -l
  fi

  i=1
  for session in "${sessions[@]}"; do
    printf "%2d) %s\n" "$i" "$session"
    i=$((i + 1))
  done
  echo
  read -rp "Select session number, or press Enter for shell: " choice
  if [ -z "$choice" ]; then
    exec bash -l
  fi
  if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#sessions[@]}" ]; then
    exec tmux attach-session -t "${sessions[$((choice - 1))]}"
  fi
done
PICKER_EOF
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
