#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/can-ops-refresh.py" "$HOME/.local/bin/can-ops-refresh"
"$HOME/.local/bin/can-ops-refresh" "$@"
