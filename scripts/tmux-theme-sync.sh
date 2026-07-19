#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$HOME/.local/bin" "$HOME/.config/tmux-theme-sync" "$HOME/.codex"

cat > "$HOME/.config/tmux-theme-sync/source" <<'EOF'
repo=cansitki/tmux-theme-sync
baseline_commit=951f624
baseline_subject=Make Codex light and dark themes switch live
runtime=ai-dev-template-hardened
EOF

install -m 0755 /dev/stdin "$HOME/.local/bin/tmux-theme" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

state_file="${CODEX_TMUX_THEME_FILE:-$HOME/.codex/tmux-theme}"
codex_config_file="${CODEX_CONFIG_FILE:-$HOME/.codex/config.toml}"

usage() {
  cat <<'EOF'
Usage: tmux-theme light|dark|off|reapply|status|check [mode]

Switches the terminal, tmux chrome, and Codex TUI between light and dark.
EOF
}

read_mode() {
  local mode=""
  if [[ -r "$state_file" ]]; then
    IFS= read -r mode < "$state_file" || true
  fi
  case "$mode" in
    dark|light|off) printf '%s\n' "$mode" ;;
    *) printf 'dark\n' ;;
  esac
}

read_stored_mode() {
  local mode=""
  if [[ -r "$state_file" ]]; then
    IFS= read -r mode < "$state_file" || true
  fi
  case "$mode" in
    dark|light|off) printf '%s\n' "$mode" ;;
    *) return 1 ;;
  esac
}

write_mode() {
  local mode="$1"
  local tmp

  mkdir -p "$(dirname "$state_file")"
  tmp="$(mktemp "${state_file}.tmp.XXXXXX")"
  if ! printf '%s\n' "$mode" > "$tmp" || ! chmod 600 "$tmp" || ! mv -f "$tmp" "$state_file"; then
    rm -f "$tmp"
    return 1
  fi
}

colors_for_mode() {
  case "$1" in
    dark) printf '%s %s\n' '#dcddde' '#1e1e1e' ;;
    light) printf '%s %s\n' '#222222' '#ffffff' ;;
    *) return 1 ;;
  esac
}

codex_tui_theme_for_mode() {
  case "$1" in
    dark) printf '%s\n' 'base16-ocean-dark' ;;
    light) printf '%s\n' 'base16-ocean-light' ;;
    *) return 1 ;;
  esac
}

set_codex_tui_theme() {
  local theme="$1"
  local tmp

  mkdir -p "$(dirname "$codex_config_file")"

  if [[ ! -f "$codex_config_file" ]]; then
    printf '[tui]\ntheme = "%s"\n' "$theme" > "$codex_config_file"
    chmod 600 "$codex_config_file"
    return 0
  fi

  tmp="$(mktemp "${codex_config_file}.tmp.XXXXXX")"
  awk -v theme="$theme" '
    BEGIN { in_tui = 0; seen_tui = 0; wrote = 0 }
    /^\[tui\][[:space:]]*$/ {
      if (in_tui && !wrote) { print "theme = \"" theme "\""; wrote = 1 }
      in_tui = 1; seen_tui = 1; print; next
    }
    /^\[/ {
      if (in_tui && !wrote) { print "theme = \"" theme "\""; wrote = 1 }
      in_tui = 0; print; next
    }
    in_tui && /^[[:space:]]*theme[[:space:]]*=/ {
      if (!wrote) { print "theme = \"" theme "\""; wrote = 1 }
      next
    }
    { print }
    END {
      if (seen_tui && in_tui && !wrote) print "theme = \"" theme "\""
      if (!seen_tui) {
        print ""
        print "[tui]"
        print "theme = \"" theme "\""
      }
    }
  ' "$codex_config_file" > "$tmp"
  mv "$tmp" "$codex_config_file"
  chmod 600 "$codex_config_file"
}

osc_sequence() {
  local fg="$1" bg="$2"
  printf '\033]10;%s\007\033]11;%s\007' "$fg" "$bg"
  printf '\033Ptmux;\033\033]10;%s\007\033\\' "$fg"
  printf '\033Ptmux;\033\033]11;%s\007\033\\' "$bg"
}

tmux_styles_for_mode() {
  case "$1" in
    dark)
      printf '%s\n' \
        'bg=#1e1e1e,fg=#dcddde' \
        'bg=#3f3f46,fg=#f4f4f5' \
        'bg=#18181b,fg=#facc15' \
        'bg=#374151,fg=#f9fafb' \
        'fg=#4b5563' \
        'fg=#60a5fa' \
        'bg=#1e1e1e,fg=#a1a1aa' \
        'bg=#3f3f46,fg=#ffffff,bold'
      ;;
    light)
      printf '%s\n' \
        'bg=#e5e7eb,fg=#111827' \
        'bg=#fef3c7,fg=#111827' \
        'bg=#ffffff,fg=#92400e' \
        'bg=#bfdbfe,fg=#111827' \
        'fg=#9ca3af' \
        'fg=#2563eb' \
        'bg=#e5e7eb,fg=#4b5563' \
        'bg=#ffffff,fg=#111827,bold'
      ;;
    *) return 1 ;;
  esac
}

apply_tmux_styles() {
  local mode="$1"
  local styles=()
  mapfile -t styles < <(tmux_styles_for_mode "$mode")

  tmux set-option -g status-style "${styles[0]}"
  tmux set-option -g message-style "${styles[1]}"
  tmux set-option -g message-command-style "${styles[2]}"
  tmux set-window-option -g mode-style "${styles[3]}"
  tmux set-window-option -g pane-border-style "${styles[4]}"
  tmux set-window-option -g pane-active-border-style "${styles[5]}"
  tmux set-window-option -g window-status-style "${styles[6]}"
  tmux set-window-option -g window-status-current-style "${styles[7]}"
}

style_contains_all_tokens() {
  local actual="$1" expected="$2" token
  while IFS= read -r token; do
    [[ -n "$token" ]] || continue
    case ",$actual," in
      *",$token,"*) ;;
      *) return 1 ;;
    esac
  done < <(printf '%s\n' "$expected" | tr ',' '\n')
}

tmux_styles_match_mode() {
  local mode="$1"
  local styles=() actual

  command -v tmux >/dev/null 2>&1 || return 0
  tmux list-sessions >/dev/null 2>&1 || return 0
  mapfile -t styles < <(tmux_styles_for_mode "$mode")

  actual="$(tmux show-options -gv status-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[0]}" || return 1
  actual="$(tmux show-options -gv message-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[1]}" || return 1
  actual="$(tmux show-options -gv message-command-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[2]}" || return 1
  actual="$(tmux show-window-options -gv mode-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[3]}" || return 1
  actual="$(tmux show-window-options -gv pane-border-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[4]}" || return 1
  actual="$(tmux show-window-options -gv pane-active-border-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[5]}" || return 1
  actual="$(tmux show-window-options -gv window-status-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[6]}" || return 1
  actual="$(tmux show-window-options -gv window-status-current-style 2>/dev/null || true)"
  style_contains_all_tokens "$actual" "${styles[7]}" || return 1
}

apply_to_tmux() {
  local mode="$1" fg="$2" bg="$3"

  if ! command -v tmux >/dev/null 2>&1; then
    return 0
  fi
  if ! tmux list-sessions >/dev/null 2>&1; then
    return 0
  fi

  tmux set-option -g allow-passthrough on 2>/dev/null || true
  apply_tmux_styles "$mode"

  while IFS= read -r win; do
    [[ -n "$win" ]] || continue
    tmux set-window-option -t "$win" allow-passthrough on >/dev/null 2>&1 || true
  done < <(tmux list-windows -a -F '#S:#I' 2>/dev/null || true)

  while IFS= read -r tty; do
    [[ -n "$tty" && -w "$tty" ]] || continue
    osc_sequence "$fg" "$bg" > "$tty" || true
  done < <(tmux list-panes -a -F '#{pane_tty}' 2>/dev/null | sort -u || true)

  while IFS= read -r tty; do
    [[ -n "$tty" && -w "$tty" ]] || continue
    osc_sequence "$fg" "$bg" > "$tty" || true
  done < <(tmux list-clients -F '#{client_tty}' 2>/dev/null | sort -u || true)
}

redraw_codex_panes() {
  if ! command -v tmux >/dev/null 2>&1 || ! command -v ps >/dev/null 2>&1; then
    return 0
  fi

  local pane tty
  while IFS=' ' read -r pane tty; do
    [[ -n "$pane" && -n "$tty" ]] || continue
    if ps -t "$tty" -o comm= 2>/dev/null | awk '{print $1}' | grep -qx 'codex'; then
      tmux send-keys -t "$pane" Escape '[' 'O' >/dev/null 2>&1 || true
      sleep 0.05
      tmux send-keys -t "$pane" Escape '[' 'I' >/dev/null 2>&1 || true
    fi
  done < <(tmux list-panes -a -F '#S:#I.#P #{pane_tty}' 2>/dev/null || true)
}

mode="${1:-status}"

case "$mode" in
  -h|--help|help)
    usage
    exit 0
    ;;
  status)
    printf 'tmux-theme: %s\n' "$(read_mode)"
    exit 0
    ;;
  check)
    mode="${2:-$(read_mode)}"
    case "$mode" in
      light|dark) ;;
      off)
        [[ "$(read_stored_mode 2>/dev/null || true)" == "off" ]] || exit 1
        exit 0
        ;;
      *) usage >&2; exit 2 ;;
    esac
    expected_theme="$(codex_tui_theme_for_mode "$mode")"
    actual_theme="$(awk -F'"' '/^[[:space:]]*theme[[:space:]]*=/{print $2; exit}' "$codex_config_file" 2>/dev/null || true)"
    [[ "$(read_stored_mode 2>/dev/null || true)" == "$mode" ]] || exit 1
    [[ "$actual_theme" == "$expected_theme" ]] || exit 1
    tmux_styles_match_mode "$mode" || exit 1
    exit 0
    ;;
  reapply)
    mode="$(read_mode)"
    write_mode "$mode"
    ;;
  light|dark|off)
    write_mode "$mode"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ "$mode" == "off" ]]; then
  printf 'tmux-theme: off\n'
  exit 0
fi

read -r fg bg < <(colors_for_mode "$mode")
set_codex_tui_theme "$(codex_tui_theme_for_mode "$mode")"

if [[ -t 1 ]]; then
  osc_sequence "$fg" "$bg"
fi

apply_to_tmux "$mode" "$fg" "$bg"
redraw_codex_panes
printf 'tmux-theme: %s\n' "$mode"
SCRIPT

install -m 0755 /dev/stdin "$HOME/.local/bin/tmux-theme-sync-poll" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

env_file="${TMUX_THEME_ENV_FILE:-$HOME/.config/tmux-theme-sync/env}"
if [[ -r "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi
if [[ -r "$HOME/main.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$HOME/main.env"
  set +a
fi

theme_url="${TMUX_THEME_SYNC_URL:-}"
token="${TMUX_THEME_SYNC_TOKEN:-}"
state_file="${CODEX_TMUX_THEME_FILE:-$HOME/.codex/tmux-theme}"
interval="${TMUX_THEME_SYNC_INTERVAL:-5}"
theme_command="${TMUX_THEME_COMMAND:-$HOME/.local/bin/tmux-theme}"

if [[ -z "$theme_url" || -z "$token" ]]; then
  echo "tmux-theme-sync-poll: TMUX_THEME_SYNC_URL and TMUX_THEME_SYNC_TOKEN are required" >&2
  exit 2
fi

read_local_mode() {
  local mode=""
  if [[ -r "$state_file" ]]; then
    IFS= read -r mode < "$state_file" || true
  fi
  case "$mode" in
    light|dark|off) printf '%s\n' "$mode" ;;
    *) printf 'dark\n' ;;
  esac
}

while true; do
  remote_mode="$(
    curl -fsS \
      -H "Authorization: Bearer ${token}" \
      "${theme_url%/}/theme" |
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("mode",""))' 2>/dev/null || true
  )"

  case "$remote_mode" in
    light|dark|off)
      if [[ "$remote_mode" != "$(read_local_mode)" ]] || ! "$theme_command" check "$remote_mode" >/dev/null 2>&1; then
        "$theme_command" "$remote_mode" >/dev/null
        echo "tmux-theme-sync-poll: applied $remote_mode"
      fi
      ;;
  esac

  sleep "$interval"
done
SCRIPT

install -m 0755 /dev/stdin "$HOME/.local/bin/tmux-theme-sync-start" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

session="${TMUX_THEME_SYNC_SESSION:-tmux-theme-sync}"
cmd="${TMUX_THEME_SYNC_POLL_CMD:-$HOME/.local/bin/tmux-theme-sync-poll}"
disabled_file="${TMUX_THEME_SYNC_DISABLED_FILE:-$HOME/.config/tmux-theme-sync/disabled}"

if [[ -e "$disabled_file" ]]; then
  echo "tmux-theme-sync-start: disabled by $disabled_file" >&2
  exit 75
fi

if tmux has-session -t "$session" 2>/dev/null; then
  tmux send-keys -t "$session:0.0" C-c
  sleep 0.2
  tmux kill-session -t "$session" 2>/dev/null || true
fi

tmux new-session -d -s "$session" "$cmd"
tmux set-option -t "$session" @nomarh_scope system
tmux display-message "started $session"
SCRIPT

install -m 0755 /dev/stdin "$HOME/.local/bin/tmux-theme-sync-stop" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

session="${TMUX_THEME_SYNC_SESSION:-tmux-theme-sync}"
if tmux has-session -t "$session" 2>/dev/null; then
  tmux kill-session -t "$session"
  echo "stopped $session"
else
  echo "$session is not running"
fi
SCRIPT

install -m 0755 /dev/stdin "$HOME/.local/bin/tmux-theme-sync-disable" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

disabled_file="${TMUX_THEME_SYNC_DISABLED_FILE:-$HOME/.config/tmux-theme-sync/disabled}"
mkdir -p "$(dirname "$disabled_file")"
printf 'disabled_at=%s\n' "$(date -u +%FT%TZ)" > "$disabled_file"
"$HOME/.local/bin/tmux-theme-sync-stop" >/dev/null 2>&1 || true
echo "tmux-theme-sync disabled"
SCRIPT

install -m 0755 /dev/stdin "$HOME/.local/bin/tmux-theme-sync-enable" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

disabled_file="${TMUX_THEME_SYNC_DISABLED_FILE:-$HOME/.config/tmux-theme-sync/disabled}"
rm -f "$disabled_file"
"$HOME/.local/bin/tmux-theme-sync-start"
SCRIPT

python3 - "$HOME/.config/tmux-theme-sync/env" <<'PY'
import os
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
existing = {}
if path.is_file():
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError:
            continue
        existing[key] = parsed[0] if parsed else ""

configured_token = os.environ.get("TMUX_THEME_SYNC_TOKEN", "")
values = {
    "TMUX_THEME_SYNC_URL": os.environ.get("TMUX_THEME_SYNC_URL", "https://theme.nomarh.com"),
    "TMUX_THEME_SYNC_ENABLED": os.environ.get("TMUX_THEME_SYNC_ENABLED", "true"),
    "TMUX_THEME_SYNC_TOKEN": configured_token or existing.get("TMUX_THEME_SYNC_TOKEN", ""),
    "TMUX_THEME_SYNC_INTERVAL": os.environ.get("TMUX_THEME_SYNC_INTERVAL", "5"),
}
path.parent.mkdir(parents=True, exist_ok=True)
lines = [f"{key}={shlex.quote(value)}\n" for key, value in values.items() if value]
path.write_text("".join(lines), encoding="utf-8")
path.chmod(0o600)
PY

if [[ -r "$HOME/.config/tmux-theme-sync/env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$HOME/.config/tmux-theme-sync/env"
  set +a
fi

# Keep tlist available for the real tmux session picker.
if [[ -f "$HOME/.zshrc" ]]; then
  sed -i '/^alias tlist="tmux-theme"$/d' "$HOME/.zshrc"
fi

if ! grep -q '# Tmux theme aliases' "$HOME/.zshrc" 2>/dev/null; then
  cat >> "$HOME/.zshrc" <<'EOF'

# Tmux theme aliases
alias tlight="tmux-theme light"
alias tdark="tmux-theme dark"
alias codex-theme="tmux-theme"
alias tsync-on="tmux-theme-sync-enable"
alias tsync-off="tmux-theme-sync-disable"
EOF
fi

# Reapply every startup so an absent/invalid state becomes dark and the Codex
# config is repaired before a fresh TUI starts, even when remote sync is off.
"$HOME/.local/bin/tmux-theme" reapply >/dev/null

# If the managed Codex runtime is installed, repair its current light/dark state
# and stable wrapper, then validate the active release. A damaged or incomplete
# optional manager must remain visible without blocking workspace startup.
codex_theme_guard="$HOME/.local/libexec/codex-theme-manager/codex-theme-guard"
if [[ -e "$codex_theme_guard" ]]; then
  if [[ ! -x "$codex_theme_guard" ]]; then
    printf 'tmux-theme-sync: warning: Codex theme guard is not executable: %s\n' "$codex_theme_guard" >&2
  elif ! "$codex_theme_guard" \
    --repair-state \
    --repair-wrapper \
    --check-wrapper \
    --quiet; then
    printf 'tmux-theme-sync: warning: Codex theme manager self-heal failed; workspace startup will continue\n' >&2
  fi
fi

theme_sync_enabled="${TMUX_THEME_SYNC_ENABLED:-true}"
case "${theme_sync_enabled,,}" in
  0|false|no|off) "$HOME/.local/bin/tmux-theme-sync-disable" || true ;;
esac

if [ -e "$HOME/.config/tmux-theme-sync/disabled" ]; then
  echo "tmux-theme-sync installed but disabled; run tmux-theme-sync-enable to start polling."
elif [ -n "${TMUX_THEME_SYNC_URL:-}" ] && [ -n "${TMUX_THEME_SYNC_TOKEN:-}" ]; then
  "$HOME/.local/bin/tmux-theme-sync-start" || true
  "$HOME/.local/bin/tmux-theme" status || true
else
  echo "tmux-theme-sync installed; set TMUX_THEME_SYNC_URL and TMUX_THEME_SYNC_TOKEN to enable polling."
fi
