#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/control-plane-restic-backup.py" "$HOME/.local/bin/control-plane-restic-backup"
"$HOME/.local/bin/control-plane-restic-backup" "$@"
