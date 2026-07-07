#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/control-plane-r2-restic-intake.py" "$HOME/.local/bin/control-plane-r2-restic-intake"
"$HOME/.local/bin/control-plane-r2-restic-intake" "$@"
