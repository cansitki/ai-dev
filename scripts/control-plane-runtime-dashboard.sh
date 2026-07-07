#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/control-plane-runtime-dashboard.py" "$HOME/.local/bin/control-plane-runtime-dashboard"
"$HOME/.local/bin/control-plane-runtime-dashboard" "$@"
