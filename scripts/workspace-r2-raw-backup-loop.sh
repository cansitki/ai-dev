#!/usr/bin/env bash
set -Eeuo pipefail

mkdir -p "$HOME/.local/bin"
install -m 0755 /dev/stdin "$HOME/.local/bin/workspace-r2-raw-backup-loop" <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Europe/Bucharest}"

SOURCE_DIR="${WORKSPACE_RAW_SOURCE:-$HOME}"
RCLONE_REMOTE="${WORKSPACE_R2_REMOTE:-r2}"
R2_BUCKET="${WORKSPACE_R2_BUCKET:-vm-backup}"
R2_PREFIX="${WORKSPACE_R2_PREFIX:-workspace-raw/main-workspace}"
BACKUP_TIMES="${WORKSPACE_R2_BACKUP_TIMES:-00:45 03:45 06:45 09:45 12:45 15:45 18:45 21:45}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/workspace-r2-raw-backup"
LOG_FILE="$STATE_DIR/workspace-r2-raw-backup.log"
STATUS_FILE="$STATE_DIR/status.json"
LOCK_FILE="$STATE_DIR/lock"
EXCLUDE_FILE="$STATE_DIR/excludes.txt"

mkdir -p "$STATE_DIR"

cat > "$EXCLUDE_FILE" <<'EOF'
/.cache/**
/.npm/**
/.pnpm-store/**
/.local/share/code-server/**
/.local/share/Trash/**
/.local/lib/node_modules/**
/.nvm/**
/.bun/install/cache/**
/.cargo/registry/**
/.rustup/**
/Can/**
/Can/workspace-raw/**
/.obsidian-cli.sock
/.config/obsidian/Cache/**
/.config/obsidian/Code Cache/**
/.config/obsidian/DawnGraphiteCache/**
/.config/obsidian/DawnWebGPUCache/**
/.config/obsidian/GPUCache/**
/.config/obsidian/IndexedDB/**
/.config/obsidian/Local Storage/**
/.config/obsidian/WebStorage/**
/.config/obsidian/.org.chromium.Chromium.*
/.config/obsidian/Singleton*
/.config/obsidian/DIPS*
/.config/obsidian/TransportSecurity
/.config/obsidian/obsidian.log
/.codex/log/**
/.codex/*.sqlite*
/.codex/models_cache.json
/.codex/history.jsonl
/.codex/sessions/**
/.codex/tmp/**
/.gsd/sessions/**
/.openclaw/agents/*/agent/codex-home/tmp/**
/.openclaw/agents/*/agent/codex-home/*.sqlite*
/.openclaw/orchestrators/*/runs/**
/.openclaw/orchestrators/*/state/**
/.local/state/*backup/*.log
/.local/state/*backup/status.json
/projects/discord-bot/data/*.db*
/projects/seed-checker/outputs/**
**/.git/**
**/node_modules/**
**/.venv/**
**/venv/**
**/__pycache__/**
**/.pytest_cache/**
**/dist/**
**/build/**
**/.next/**
**/.turbo/**
**/target/**
**/*.pyc
**/*.sqlite-wal
**/*.sqlite-shm
**/*.db-wal
**/*.db-shm
**/*.lock
**/*.log
**/core
**/core.*
EOF

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" | tee -a "$LOG_FILE"
}

release_lock() {
  flock -u 9 2>/dev/null || true
  exec 9>&- 2>/dev/null || true
}

json_string() {
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

create_live_state_snapshots() {
  local snapshot_root tmp_root
  snapshot_root="$SOURCE_DIR/backups/workspace-live-state/current"
  tmp_root="$SOURCE_DIR/backups/workspace-live-state/.current.tmp"

  rm -rf "$tmp_root"
  mkdir -p "$tmp_root"

  if ! python3 - "$SOURCE_DIR" "$tmp_root" <<'PY'
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

source = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
manifest = {
    "created_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "schema": "workspace-live-state-snapshot.v1",
    "sqlite_snapshots": [],
    "archives": [],
    "errors": [],
}

def safe_rel(path: Path) -> Path:
    rel = path.resolve().relative_to(source)
    if any(part in {".env", ".ssh", "credentials"} for part in rel.parts):
        raise ValueError(f"refusing sensitive path: {rel}")
    return rel

def snapshot_sqlite(src: Path, dst_rel: Path) -> None:
    if not src.is_file():
        return
    dst = root / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_db = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5)
        try:
            target_db = sqlite3.connect(dst)
            try:
                source_db.backup(target_db)
            finally:
                target_db.close()
        finally:
            source_db.close()
        manifest["sqlite_snapshots"].append({"source": str(safe_rel(src)), "snapshot": str(dst_rel), "mode": "sqlite_backup"})
    except Exception as exc:
        manifest["errors"].append({"source": str(src), "error": f"sqlite_backup_failed: {exc}"})
        try:
            shutil.copy2(src, dst)
            manifest["sqlite_snapshots"].append({"source": str(safe_rel(src)), "snapshot": str(dst_rel), "mode": "copy2_fallback"})
        except Exception as copy_exc:
            manifest["errors"].append({"source": str(src), "error": f"copy_fallback_failed: {copy_exc}"})

snapshot_sqlite(source / "projects/discord-bot/data/bot.db", Path("discord-bot/data/bot.db"))

agent_root = source / ".openclaw/agents"
if agent_root.is_dir():
    for db in sorted(agent_root.glob("*/agent/codex-home/*.sqlite")):
        agent = db.parts[-4]
        snapshot_sqlite(db, Path("openclaw-agent-sqlite") / agent / db.name)

def archive_selected(name: str, patterns: list[str], max_file_bytes: int = 50 * 1024 * 1024) -> None:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(p for p in source.glob(pattern) if p.is_file())
    files = sorted(set(files))
    if not files:
        return
    out = root / name
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(out, "w:gz") as tar:
        for path in files:
            try:
                rel = safe_rel(path)
                if path.stat().st_size > max_file_bytes:
                    manifest["errors"].append({"source": str(rel), "error": "skipped_oversize"})
                    continue
                tar.add(path, arcname=str(rel), recursive=False)
                count += 1
            except Exception as exc:
                manifest["errors"].append({"source": str(path), "error": f"archive_failed: {exc}"})
    manifest["archives"].append({"archive": name, "files": count})

archive_selected(
    "openclaw-orchestrator-state.tar.gz",
    [
        ".openclaw/orchestrators/*/state/**/*.json",
        ".openclaw/orchestrators/*/state/**/*.jsonl",
    ],
)
archive_selected(
    "gsd-sessions.tar.gz",
    [
        ".gsd/sessions/**/*.jsonl",
    ],
)

(root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  then
    log "live-state snapshot failed; continuing raw backup without refreshed snapshots"
    rm -rf "$tmp_root"
    return 0
  fi

  rm -rf "$snapshot_root"
  mv "$tmp_root" "$snapshot_root"
  log "live-state snapshot refreshed at $snapshot_root"
}

write_status() {
  local state="$1"
  local message="$2"
  local next_run="${3:-}"
  local uploaded="${4:-}"
  cat > "$STATUS_FILE" <<EOF
{
  "state": $(json_string "$state"),
  "message": $(json_string "$message"),
  "updated_at": $(json_string "$(date --iso-8601=seconds)"),
  "next_run": $(json_string "$next_run"),
  "source": $(json_string "$SOURCE_DIR"),
  "destination": $(json_string "$RCLONE_REMOTE:$R2_BUCKET/$R2_PREFIX/current"),
  "mode": "raw-rclone-copy-no-delete",
  "uploaded": $(json_string "$uploaded")
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
  local next_epoch now_epoch seconds
  next_epoch="$(date -d "$(next_run_iso)" '+%s')"
  now_epoch="$(date '+%s')"
  seconds=$((next_epoch - now_epoch))
  if [ "$seconds" -lt 1 ]; then
    seconds=1
  fi
  sleep "$seconds"
}

run_backup() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "another raw R2 backup is already running"
    exec 9>&- 2>/dev/null || true
    return 0
  fi

  if ! command -v rclone >/dev/null 2>&1; then
    log "rclone is not installed"
    write_status "error" "rclone is not installed"
    release_lock
    return 1
  fi

  if ! rclone listremotes | grep -qx "${RCLONE_REMOTE}:"; then
    log "rclone remote missing: $RCLONE_REMOTE"
    write_status "error" "rclone remote missing"
    release_lock
    return 1
  fi

  local started stamp dest output rc
  started="$(date --iso-8601=seconds)"
  stamp="$(date '+%Y%m%d-%H%M%S')"
  dest="$RCLONE_REMOTE:$R2_BUCKET/$R2_PREFIX/current"

  log "raw R2 backup started: $SOURCE_DIR -> $dest"
  write_status "running" "raw R2 backup running" "$(next_run_iso)"
  create_live_state_snapshots

  set +e
  output="$(
    rclone copy "$SOURCE_DIR" "$dest" \
      --exclude-from "$EXCLUDE_FILE" \
      --no-update-modtime \
      --fast-list \
      --transfers 8 \
      --checkers 16 \
      --s3-upload-concurrency 4 \
      --stats 1m \
      --stats-one-line \
      --log-level INFO 2>&1
  )"
  rc=$?
  set -e

  printf '%s\n' "$output" >> "$LOG_FILE"
  if [ "$rc" -ne 0 ]; then
    log "raw R2 backup failed with exit code $rc"
    write_status "error" "raw R2 backup failed" "$(next_run_iso)"
    release_lock
    return "$rc"
  fi

  log "raw R2 backup completed; started $started"
  write_status "success" "raw R2 backup completed" "$(next_run_iso)" "$(printf '%s\n' "$output" | tail -20)"
  release_lock
}

case "${1:-loop}" in
  once)
    run_backup
    ;;
  loop)
    log "raw R2 backup loop started for 8 runs/day ($BACKUP_TIMES) $TZ"
    while true; do
      next="$(next_run_iso)"
      write_status "sleeping" "waiting for next raw R2 backup" "$next"
      log "next raw R2 backup: $next"
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

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone is not installed; raw R2 backup script installed but not started."
  exit 0
fi

if ! rclone listremotes | grep -qx 'r2:'; then
  echo "rclone remote 'r2' is not configured; raw R2 backup script installed but not started."
  exit 0
fi

if tmux has-session -t vm-r2-backup 2>/dev/null; then
  echo "vm-r2-backup tmux session already running"
  exit 0
fi

tmux new-session -d -s vm-r2-backup -c "$HOME" "$HOME/.local/bin/workspace-r2-raw-backup-loop"
echo "vm-r2-backup tmux session started"
