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
NOVNC_PORT=6080
OBSIDIAN_SESSION=obsidian-headless
OBSIDIAN_BIN=/opt/Obsidian/obsidian
VAULT_DIR="${OBSIDIAN_VAULT_DIR:-$HOME/Can}"
VAULT_LINK="$HOME/vault"
OBSIDIAN_RUNNER="$HOME/.local/bin/obsidian-headless-loop"

mkdir -p "$HOME/.config/obsidian"
mkdir -p "$HOME/.local/bin"
mkdir -p "$VAULT_DIR"

# Keep ~/vault as the convention alias, but do not destroy a real vault if a
# future workspace has mounted or restored one there.
if [ ! -e "$VAULT_LINK" ]; then
    ln -s "$VAULT_DIR" "$VAULT_LINK"
elif [ -d "$VAULT_LINK" ] && [ ! -L "$VAULT_LINK" ] && [ -z "$(find "$VAULT_LINK" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    rmdir "$VAULT_LINK"
    ln -s "$VAULT_DIR" "$VAULT_LINK"
elif [ -L "$VAULT_LINK" ] && [ "$(readlink "$VAULT_LINK")" != "$VAULT_DIR" ]; then
    ln -sfn "$VAULT_DIR" "$VAULT_LINK"
fi

obsidian_running() {
    pgrep -u "$USER" -f "^${OBSIDIAN_BIN} .*--no-sandbox" > /dev/null
}

# --- Xvfb ---
if ! pgrep -f "Xvfb :${DISPLAY_NUM}" > /dev/null; then
    echo -e "${BOLD}Starting Xvfb on :${DISPLAY_NUM}${NC}"
    Xvfb ":${DISPLAY_NUM}" -screen 0 1920x1080x24 -nolisten tcp > /dev/null 2>&1 &
    sleep 1
fi

export DISPLAY=":${DISPLAY_NUM}"

# --- D-Bus session (required by Obsidian + obsidian CLI) ---
if [ -f "$HOME/.dbus-env" ]; then
    # shellcheck disable=SC1091
    source "$HOME/.dbus-env"
fi
DBUS_SOCKET=""
if [[ "${DBUS_SESSION_BUS_ADDRESS:-}" == unix:path=* ]]; then
    DBUS_SOCKET="${DBUS_SESSION_BUS_ADDRESS#unix:path=}"
    DBUS_SOCKET="${DBUS_SOCKET%%,*}"
fi
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] || [ -z "$DBUS_SOCKET" ] || [ ! -S "$DBUS_SOCKET" ]; then
    echo -e "${BOLD}Starting D-Bus session${NC}"
    eval "$(dbus-launch --sh-syntax)"
    # Persist for other shells
    echo "export DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}'" > "$HOME/.dbus-env"
    echo "export DISPLAY=':${DISPLAY_NUM}'" >> "$HOME/.dbus-env"
fi

# --- Obsidian Desktop ---
# Use the actual Desktop binary. PATH often resolves `obsidian` to the CLI
# helper in ~/.local/bin, which cannot start the app and leaves a stale socket.
if ! obsidian_running; then
    echo -e "${BOLD}Starting Obsidian (headless)${NC}"
    rm -f "$HOME/.obsidian-cli.sock"
    cat > "$OBSIDIAN_RUNNER" <<EOF
#!/bin/bash
source "$HOME/.dbus-env" 2>/dev/null || true
export DISPLAY=":${DISPLAY_NUM}"

while true; do
    rm -f "$HOME/.obsidian-cli.sock"
    "$OBSIDIAN_BIN" --no-sandbox --disable-gpu "$VAULT_DIR" >> "$HOME/.config/obsidian/obsidian.log" 2>&1
    status=\$?
    printf '[%s] Obsidian exited with status %s; restarting in 5s\n' "\$(date -Is)" "\$status" >> "$HOME/.config/obsidian/obsidian.log"
    sleep 5
done
EOF
    chmod +x "$OBSIDIAN_RUNNER"
    tmux kill-session -t "${OBSIDIAN_SESSION}" 2>/dev/null || true
    tmux new-session -d -s "${OBSIDIAN_SESSION}" "$OBSIDIAN_RUNNER"
    for _ in {1..10}; do
        if obsidian_running; then
            break
        fi
        sleep 1
    done
    if obsidian_running; then
        echo -e "${GREEN}Obsidian started${NC}"
    else
        echo -e "${YELLOW}Obsidian did not start — check ~/.config/obsidian/obsidian.log${NC}"
        tmux capture-pane -pt "${OBSIDIAN_SESSION}" -S -80 2>/dev/null || true
        exit 1
    fi
fi

# --- VNC bridge for one-time GUI access (login to Obsidian Sync) ---
if ! pgrep -f "x11vnc.*:${DISPLAY_NUM}" > /dev/null; then
    echo -e "${BOLD}Starting x11vnc on port ${VNC_PORT}${NC}"
    x11vnc -display ":${DISPLAY_NUM}" -rfbport "${VNC_PORT}" \
           -nopw -shared -forever -bg -o "$HOME/.config/obsidian/x11vnc.log" \
           > /dev/null 2>&1 || true
fi

# --- noVNC HTTP/WebSocket bridge so Coder's app proxy can serve the GUI ---
if ! tmux has-session -t novnc 2>/dev/null; then
    echo -e "${BOLD}Starting noVNC bridge on port ${NOVNC_PORT}${NC}"
    tmux new-session -d -s novnc "websockify --web=/usr/share/novnc ${NOVNC_PORT} localhost:${VNC_PORT}"
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
