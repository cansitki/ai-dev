#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/can-ops-scheduler.py" "$HOME/.local/bin/can-ops-scheduler"
"$HOME/.local/bin/can-ops-scheduler" "$@"
