#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

SOURCE_DIR="${NOMARH_TEMPLATE_SCRIPTS_DIR:-/opt/ai-dev-template/scripts}"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "nomarh-ops-toolkit: source directory missing: $SOURCE_DIR" >&2
  exit 1
fi

install_python_command() {
  local path="$1"
  local name
  name="$(basename "$path" .py)"
  install -m 0755 "$path" "$BIN_DIR/$name"
}

shopt -s nullglob
for path in \
  "$SOURCE_DIR"/can-*.py \
  "$SOURCE_DIR"/control-plane-*.py \
  "$SOURCE_DIR"/hetzner-*.py \
  "$SOURCE_DIR"/nomarh-*.py \
  "$SOURCE_DIR"/tmux-cleanup-review.py \
  "$SOURCE_DIR"/obsidian-flush-spool.py; do
  install_python_command "$path"
done

cat > "$BIN_DIR/ops" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
exec nomarh-ops --refresh "$@"
SCRIPT
chmod 0755 "$BIN_DIR/ops"

cat > "$BIN_DIR/can-morning" <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail

card_path="$HOME/.local/state/nomarh-operator-card/card.md"
brief_path="$HOME/.local/state/can-ops-brief/brief.md"
readiness_path="$HOME/.local/state/nomarh-migration-readiness/readiness.md"
state_dir="$HOME/.local/state/can-morning"
step_log="$state_dir/last-step.log"
mkdir -p "$state_dir"

run_step() {
  local label="$1"
  shift
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[skip] %s: command not found: %s\n' "$label" "$1"
    return 0
  fi
  printf '[run] %s\n' "$label"
  "$@" >"$step_log" 2>&1
  local rc=$?
  case "$rc" in
    0) printf '[ok] %s\n' "$label" ;;
    2) printf '[warn] %s returned warning/blocked status\n' "$label" ;;
    *) printf '[warn] %s exited %s; see %s\n' "$label" "$rc" "$step_log" ;;
  esac
  return 0
}

show_section() {
  local title="$1" path="$2" limit="${3:-180}"
  if [ -s "$path" ]; then
    printf '\n== %s ==\n' "$title"
    sed -n "1,${limit}p" "$path"
  fi
}

printf 'Can morning\n'
printf 'Host: %s\n' "$(hostname)"
printf 'Time: %s\n\n' "$(date -Is)"

run_step "ops refresh" can-ops-refresh --json
run_step "migration readiness" nomarh-migration-readiness --refresh --json
run_step "operator card" nomarh-operator-card --refresh --timeout "${CAN_MORNING_TIMEOUT:-240}"

show_section "Operator card" "$card_path" 220
show_section "Ops brief" "$brief_path" 180
show_section "Migration readiness" "$readiness_path" 120

printf '\nUseful follow-ups: can-doctor | tmux-cleanup-review | nomarh-action-pack --json\n'
SCRIPT
chmod 0755 "$BIN_DIR/can-morning"

cat > "$BIN_DIR/morning" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
exec can-morning "$@"
SCRIPT
chmod 0755 "$BIN_DIR/morning"

ensure_zsh_alias() {
  local name="$1"
  local value="$2"
  local line="alias ${name}=\"${value}\""
  local zshrc="$HOME/.zshrc"
  local tmp

  touch "$zshrc"
  tmp="${zshrc}.tmp.$$"
  awk -v name="$name" -v line="$line" '
    $0 ~ "^alias " name "=" {
      if (!seen) {
        print line
        seen = 1
      }
      next
    }
    { print }
    END {
      if (!seen) {
        print line
      }
    }
  ' "$zshrc" > "$tmp"
  mv "$tmp" "$zshrc"
}

if ! grep -q '# Nomarh ops aliases' "$HOME/.zshrc" 2>/dev/null; then
  cat >> "$HOME/.zshrc" <<'EOF'

# Nomarh ops aliases
alias ops="nomarh-ops --refresh"
alias operator="nomarh-operator-card --refresh"
alias ops-brief="sed -n '1,220p' ~/.local/state/can-ops-brief/brief.md"
alias ops-summary="sed -n '1,220p' ~/.local/state/nomarh-ops/summary.md"
alias ops-card="sed -n '1,220p' ~/.local/state/nomarh-operator-card/card.md"
EOF
fi

ensure_zsh_alias "morning" "can-morning"
ensure_zsh_alias "daily-start" "can-morning"
ensure_zsh_alias "ops" "nomarh-ops --refresh"
ensure_zsh_alias "operator" "nomarh-operator-card --refresh"

if [ "${NOMARH_OPS_TOOLKIT_START_SCHEDULER:-1}" = "1" ] && command -v can-ops-scheduler >/dev/null 2>&1; then
  can-ops-scheduler start --interval "${CAN_OPS_REFRESH_INTERVAL:-1800}" || true
fi

if [ "${NOMARH_OPS_TOOLKIT_RUN_DOCTOR:-1}" = "1" ] && command -v can-doctor >/dev/null 2>&1; then
  can-doctor || true
fi

echo "Installed Nomarh ops toolkit into $BIN_DIR"
