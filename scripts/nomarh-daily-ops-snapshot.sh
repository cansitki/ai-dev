#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-daily-ops-snapshot.py" "$HOME/.local/bin/nomarh-daily-ops-snapshot"
"$HOME/.local/bin/nomarh-daily-ops-snapshot" "$@"
