#!/bin/bash
# Run Obsidian Desktop headless inside the workspace.
#
# - Xvfb provides a virtual X display (:99)
# - dbus-launch gives Obsidian the D-Bus session it needs for the CLI
# - x11vnc exposes the display so you can VNC in once for first-time
#   Sync login, then leave it running headless thereafter.
#
# State (login token, vault registration, sync settings) lives under
# ~/.config/obsidian and persists in the workspace home volume across
# rebuilds.

set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

DISPLAY_NUM=99
VNC_PORT=5999

mkdir -p "$HOME/.config/obsidian"
mkdir -p "$HOME/vault"

# --- Xvfb ---
if ! pgrep -f "Xvfb :${DISPLAY_NUM}" > /dev/null; then
    echo -e "${BOLD}Starting Xvfb on :${DISPLAY_NUM}${NC}"
    Xvfb ":${DISPLAY_NUM}" -screen 0 1920x1080x24 -nolisten tcp > /dev/null 2>&1 &
    sleep 1
fi

export DISPLAY=":${DISPLAY_NUM}"

# --- D-Bus session (required by Obsidian + obsidian CLI) ---
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] || ! pgrep -u "$USER" -x dbus-daemon > /dev/null; then
    echo -e "${BOLD}Starting D-Bus session${NC}"
    eval "$(dbus-launch --sh-syntax)"
    # Persist for other shells
    echo "export DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'" > "$HOME/.dbus-env"
    echo "export DISPLAY=':${DISPLAY_NUM}'" >> "$HOME/.dbus-env"
fi

# --- Obsidian Desktop ---
if ! pgrep -f "obsidian" > /dev/null; then
    echo -e "${BOLD}Starting Obsidian (headless)${NC}"
    nohup obsidian --no-sandbox > "$HOME/.config/obsidian/obsidian.log" 2>&1 &
    sleep 3
    if pgrep -f "obsidian" > /dev/null; then
        echo -e "${GREEN}Obsidian started${NC}"
    else
        echo -e "${YELLOW}Obsidian did not start — check ~/.config/obsidian/obsidian.log${NC}"
    fi
fi

# --- VNC bridge for one-time GUI access (login to Obsidian Sync) ---
if ! pgrep -f "x11vnc.*:${DISPLAY_NUM}" > /dev/null; then
    echo -e "${BOLD}Starting x11vnc on port ${VNC_PORT}${NC}"
    x11vnc -display ":${DISPLAY_NUM}" -rfbport "${VNC_PORT}" \
           -nopw -shared -forever -bg -o "$HOME/.config/obsidian/x11vnc.log" \
           > /dev/null 2>&1 || true
fi

# --- Source D-Bus env into login shells so `obsidian` CLI works ---
if ! grep -q "obsidian dbus env" "$HOME/.zshenv" 2>/dev/null; then
    cat >> "$HOME/.zshenv" <<'EOF'

# obsidian dbus env — sourced from obsidian-serve.sh
[ -f "$HOME/.dbus-env" ] && source "$HOME/.dbus-env"
EOF
fi
if ! grep -q "obsidian dbus env" "$HOME/.bashrc" 2>/dev/null; then
    cat >> "$HOME/.bashrc" <<'EOF'

# obsidian dbus env — sourced from obsidian-serve.sh
[ -f "$HOME/.dbus-env" ] && source "$HOME/.dbus-env"
EOF
fi

echo -e "${GREEN}Obsidian headless ready on :${DISPLAY_NUM}, VNC on :${VNC_PORT}${NC}"
echo -e "First-time setup: connect via the 'Obsidian VNC' Coder app and log in to Sync."
