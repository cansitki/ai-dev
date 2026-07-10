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
export TZ="${TZ:-Europe/Bucharest}"

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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_SCRIPT_DIR="${NOMARH_TEMPLATE_SCRIPTS_DIR:-/opt/ai-dev-template/scripts}"
OBSIDIAN_CLI="$HOME/.local/bin/obsidian"
OBSIDIAN_IPC="$HOME/.local/bin/obsidian-ipc"
OBSIDIAN_DESKTOP_CLI=/opt/Obsidian/obsidian-cli
OBSIDIAN_FLUSHER="$HOME/.local/bin/obsidian-flush-spool"
OBSIDIAN_TMP_DIR="$HOME/.cache/obsidian-tmp"

mkdir -p "$HOME/.config/obsidian"
mkdir -p "$HOME/.local/bin"
mkdir -p "$VAULT_DIR"
mkdir -p "$OBSIDIAN_TMP_DIR"
chmod 700 "$OBSIDIAN_TMP_DIR" 2>/dev/null || true

# Keep the raw IPC client available as obsidian-ipc, then put a wrapper at
# ~/.local/bin/obsidian so final daily logging cannot falsely fail completed
# agent tasks if Obsidian Desktop crashes while acknowledging the append.
if [ -x "$OBSIDIAN_CLI" ] && ! grep -q "obsidian-flush-spool" "$OBSIDIAN_CLI" 2>/dev/null; then
    if [ ! -e "$OBSIDIAN_IPC" ]; then
        mv "$OBSIDIAN_CLI" "$OBSIDIAN_IPC"
        chmod 0755 "$OBSIDIAN_IPC"
    fi
fi
if [ ! -x "$OBSIDIAN_IPC" ] && [ -x "$OBSIDIAN_DESKTOP_CLI" ]; then
    install -m 0755 "$OBSIDIAN_DESKTOP_CLI" "$OBSIDIAN_IPC"
fi

python3 - <<'PY'
import json
from pathlib import Path

home = Path.home()
config_dir = home / ".config" / "obsidian"
vault_dir = Path.home() / "Can"
config_dir.mkdir(parents=True, exist_ok=True)

config_path = config_dir / "obsidian.json"
try:
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
except Exception:
    config = {}

vaults = config.setdefault("vaults", {})
vault = vaults.setdefault("99e56272d87005fa", {})
vault["path"] = str(vault_dir)
vault["open"] = True
vault.setdefault("ts", 1779575439920)
config["cli"] = True
config_path.write_text(json.dumps(config, separators=(",", ":")) + "\n")

window_path = config_dir / "99e56272d87005fa.json"
if not window_path.exists():
    window_path.write_text(
        json.dumps(
            {
                "x": 448,
                "y": 140,
                "width": 1024,
                "height": 800,
                "isMaximized": False,
                "devTools": False,
                "zoom": 0,
            },
            separators=(",", ":"),
        )
        + "\n"
    )

vault_config_dir = vault_dir / ".obsidian"
vault_config_dir.mkdir(parents=True, exist_ok=True)
(vault_dir / "daily notes").mkdir(parents=True, exist_ok=True)
(vault_config_dir / "daily-notes.json").write_text('{"folder":"daily notes"}\n')
PY

template_file() {
    if [ -f "$SCRIPT_DIR/$1" ]; then
        printf '%s\n' "$SCRIPT_DIR/$1"
    elif [ -f "$TEMPLATE_SCRIPT_DIR/$1" ]; then
        printf '%s\n' "$TEMPLATE_SCRIPT_DIR/$1"
    fi
}

OBSIDIAN_WRAPPER_SRC="$(template_file obsidian-wrapper.sh || true)"
OBSIDIAN_FLUSHER_SRC="$(template_file obsidian-flush-spool.py || true)"

if [ -n "$OBSIDIAN_WRAPPER_SRC" ]; then
    install -m 0755 "$OBSIDIAN_WRAPPER_SRC" "$OBSIDIAN_CLI"
fi
if [ -n "$OBSIDIAN_FLUSHER_SRC" ]; then
    install -m 0755 "$OBSIDIAN_FLUSHER_SRC" "$OBSIDIAN_FLUSHER"
fi

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
export TZ="${TZ:-Europe/Bucharest}"
export DISPLAY=":${DISPLAY_NUM}"
export ELECTRON_DISABLE_GPU=1
export TMPDIR="$OBSIDIAN_TMP_DIR"
mkdir -p "\$TMPDIR"
chmod 700 "\$TMPDIR" 2>/dev/null || true
OBSIDIAN_BIN="$OBSIDIAN_BIN"
OBSIDIAN_CLI="$HOME/.local/bin/obsidian-ipc"
OBSIDIAN_LOG="$HOME/.config/obsidian/obsidian.log"
OBSIDIAN_SOCKET="$HOME/.obsidian-cli.sock"
VAULT_DIR="$VAULT_DIR"

flush_loop() {
    while true; do
        "$HOME/.local/bin/obsidian-flush-spool" --quiet --max-items 50 >/dev/null 2>&1 || true
        sleep 60
    done
}

health_loop() {
    failures=0
    sleep 45
    while true; do
        sleep 30
        app_pid="\$(pgrep -u "\$(id -un)" -f "^\${OBSIDIAN_BIN} .* \${VAULT_DIR}\$" | head -n 1 || true)"
        if [ -z "\$app_pid" ]; then
            failures=0
            continue
        fi
        if timeout 8s "\$OBSIDIAN_CLI" files total >/dev/null 2>&1; then
            failures=0
            continue
        fi
        failures=\$((failures + 1))
        printf '[%s] Obsidian IPC health check failed (%s/2); app pid %s\n' "\$(date -Is)" "\$failures" "\$app_pid" >> "\$OBSIDIAN_LOG"
        if [ "\$failures" -ge 2 ]; then
            printf '[%s] Obsidian IPC is wedged; restarting app pid %s\n' "\$(date -Is)" "\$app_pid" >> "\$OBSIDIAN_LOG"
            pkill -TERM -P "\$app_pid" 2>/dev/null || true
            kill -TERM "\$app_pid" 2>/dev/null || true
            sleep 5
            pkill -KILL -P "\$app_pid" 2>/dev/null || true
            kill -KILL "\$app_pid" 2>/dev/null || true
            rm -f "\$OBSIDIAN_SOCKET"
            failures=0
            sleep 20
        fi
    done
}

flush_loop &
flush_loop_pid=\$!
health_loop &
health_loop_pid=\$!
trap 'kill "\$flush_loop_pid" "\$health_loop_pid" 2>/dev/null || true' EXIT

while true; do
    rm -f "\$OBSIDIAN_SOCKET"
    "\$OBSIDIAN_BIN" \\
        --no-sandbox \\
        --disable-gpu \\
        --disable-gpu-sandbox \\
        --disable-dev-shm-usage \\
        --disable-gpu-compositing \\
        --disable-renderer-backgrounding \\
        --disable-background-timer-throttling \\
        --disable-features=VizDisplayCompositor \\
        "\$VAULT_DIR" >> "\$OBSIDIAN_LOG" 2>&1
    status=\$?
    printf '[%s] Obsidian exited with status %s; restarting in 5s\n' "\$(date -Is)" "\$status" >> "\$OBSIDIAN_LOG"
    sleep 5
done
EOF
    chmod +x "$OBSIDIAN_RUNNER"
    tmux kill-session -t "${OBSIDIAN_SESSION}" 2>/dev/null || true
    tmux new-session -d -s "${OBSIDIAN_SESSION}" "$OBSIDIAN_RUNNER"
    tmux set-option -t "${OBSIDIAN_SESSION}" @nomarh_scope system
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

if tmux has-session -t "${OBSIDIAN_SESSION}" 2>/dev/null; then
    tmux set-option -t "${OBSIDIAN_SESSION}" @nomarh_scope system
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
tmux set-option -t novnc @nomarh_scope system

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
