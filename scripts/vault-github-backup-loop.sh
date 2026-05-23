#!/usr/bin/env bash
set -Eeuo pipefail

mkdir -p "$HOME/.local/bin"
install -m 0755 /dev/stdin "$HOME/.local/bin/vault-github-backup-loop" <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Europe/Bucharest}"

VAULT_DIR="${VAULT_DIR:-$HOME/Can}"
REMOTE="${VAULT_REMOTE:-origin}"
BRANCH="${VAULT_BRANCH:-main}"
BACKUP_TIMES="${VAULT_BACKUP_TIMES:-00:30 03:30 06:30 09:30 12:30 15:30 18:30 21:30}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/vault-backup"
LOG_FILE="$STATE_DIR/vault-github-backup.log"
STATUS_FILE="$STATE_DIR/status.json"
LOCK_FILE="$STATE_DIR/lock"

mkdir -p "$STATE_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" | tee -a "$LOG_FILE"
}

json_string() {
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

write_status() {
  local state="$1"
  local message="$2"
  local next_run="${3:-}"
  cat > "$STATUS_FILE" <<EOF
{
  "state": $(json_string "$state"),
  "message": $(json_string "$message"),
  "updated_at": $(json_string "$(date --iso-8601=seconds)"),
  "next_run": $(json_string "$next_run"),
  "vault_dir": $(json_string "$VAULT_DIR"),
  "remote": $(json_string "$REMOTE"),
  "branch": $(json_string "$BRANCH")
}
EOF
}

next_run_iso() {
  local now_epoch best_epoch candidate t
  now_epoch="$(date '+%s')"
  best_epoch=""
  for t in $BACKUP_TIMES; do
    candidate="$(date -d "today $t" '+%s')"
    if [ "$candidate" -gt "$now_epoch" ] && { [ -z "$best_epoch" ] || [ "$candidate" -lt "$best_epoch" ]; }; then
      best_epoch="$candidate"
    fi
  done
  if [ -z "$best_epoch" ]; then
    for t in $BACKUP_TIMES; do
      candidate="$(date -d "tomorrow $t" '+%s')"
      if [ -z "$best_epoch" ] || [ "$candidate" -lt "$best_epoch" ]; then
        best_epoch="$candidate"
      fi
    done
  fi
  date -d "@$best_epoch" --iso-8601=seconds
}

sleep_until_next_run() {
  local next_epoch
  next_epoch="$(date -d "$(next_run_iso)" '+%s')"
  local now_epoch
  now_epoch="$(date '+%s')"
  local seconds=$((next_epoch - now_epoch))
  if [ "$seconds" -lt 1 ]; then
    seconds=1
  fi
  sleep "$seconds"
}

run_backup() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "another vault backup is already running"
    return 0
  fi

  if [ ! -d "$VAULT_DIR/.git" ]; then
    log "vault repo missing: $VAULT_DIR"
    write_status "error" "vault repo missing"
    return 1
  fi

  cd "$VAULT_DIR"

  gh auth setup-git >/dev/null 2>&1 || true
  git fetch "$REMOTE" "$BRANCH" --quiet

  if ! git pull --rebase --autostash "$REMOTE" "$BRANCH" --quiet; then
    log "git pull failed; leaving workspace untouched"
    write_status "error" "git pull failed"
    return 1
  fi

  git add -A

  if git diff --cached --quiet; then
    if [ "$(git rev-list --count "$REMOTE/$BRANCH"..HEAD)" -gt 0 ]; then
      git push "$REMOTE" "$BRANCH" --quiet
      log "pushed existing local commits"
      write_status "success" "pushed existing local commits" "$(next_run_iso)"
    else
      log "no vault changes to back up"
      write_status "success" "no changes" "$(next_run_iso)"
    fi
    return 0
  fi

  local stamp
  stamp="$(date '+%Y-%m-%d %H:%M %Z')"
  git -c commit.gpgsign=false commit -m "Nightly vault backup $stamp" --quiet
  git push "$REMOTE" "$BRANCH" --quiet
  log "committed and pushed vault backup: $stamp"
  write_status "success" "committed and pushed vault backup" "$(next_run_iso)"
}

case "${1:-loop}" in
  once)
    run_backup
    ;;
  loop)
    log "vault backup loop started for 8 runs/day ($BACKUP_TIMES) $TZ"
    while true; do
      next="$(next_run_iso)"
      write_status "sleeping" "waiting for next backup" "$next"
      log "next vault backup: $next"
      sleep_until_next_run
      run_backup || true
    done
    ;;
  *)
    echo "usage: $0 [once|loop]" >&2
    exit 2
    ;;
esac
SCRIPT

if [ ! -d "$HOME/Can/.git" ]; then
  echo "Vault repo not available at $HOME/Can; backup loop installed but not started."
  exit 0
fi

if tmux has-session -t vault-backup 2>/dev/null; then
  echo "vault-backup tmux session already running"
  exit 0
fi

tmux new-session -d -s vault-backup -c "$HOME" "$HOME/.local/bin/vault-github-backup-loop"
echo "vault-backup tmux session started"
