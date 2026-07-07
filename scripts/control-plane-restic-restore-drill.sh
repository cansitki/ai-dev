#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/control-plane-restic-restore-drill.py" "$HOME/.local/bin/control-plane-restic-restore-drill"
"$HOME/.local/bin/control-plane-restic-restore-drill" "$@"
