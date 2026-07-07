#!/usr/bin/env bash
set -u

REAL="${OBSIDIAN_REAL:-$HOME/.local/bin/obsidian-ipc}"
FLUSHER="${OBSIDIAN_FLUSHER:-$HOME/.local/bin/obsidian-flush-spool}"
DAILY_APPEND_TIMEOUT="${OBSIDIAN_DAILY_APPEND_TIMEOUT:-20}"

if [ "${1:-}" = "--real" ]; then
    shift
    exec "$REAL" "$@"
fi

if [ "${1:-}" = "--flush-spool" ]; then
    shift
    exec "$FLUSHER" "$@"
fi

if [ "${1:-}" != "daily:append" ]; then
    exec "$REAL" "$@"
fi

has_content=0
for arg in "$@"; do
    case "$arg" in
        content=*)
            has_content=1
            ;;
    esac
done

if [ "$has_content" -ne 1 ]; then
    exec "$REAL" "$@"
fi

out_file="$(mktemp -t obsidian-daily-append-out.XXXXXX)"
err_file="$(mktemp -t obsidian-daily-append-err.XXXXXX)"
cleanup() {
    rm -f "$out_file" "$err_file"
}
trap cleanup EXIT

timeout "${DAILY_APPEND_TIMEOUT}s" "$REAL" "$@" >"$out_file" 2>"$err_file"
status=$?

cat "$out_file"

if [ "$status" -eq 0 ]; then
    if [ -x "$FLUSHER" ]; then
        "$FLUSHER" --quiet --max-items 20 >/dev/null 2>&1 &
    fi
    exit 0
fi

cat "$err_file" >&2

if [ -x "$FLUSHER" ]; then
    "$FLUSHER" --queue --status "$status" --cwd "$PWD" -- "$@" || exit "$status"
    exit 0
fi

printf 'obsidian: daily:append failed with status %s and no spool helper is available\n' "$status" >&2
exit "$status"
