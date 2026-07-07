#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/control-plane-r2-restic-bootstrap.py" "$HOME/.local/bin/control-plane-r2-restic-bootstrap"
"$HOME/.local/bin/control-plane-r2-restic-bootstrap" "$@"
