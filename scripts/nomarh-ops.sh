#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-ops.py" "$HOME/.local/bin/nomarh-ops"
"$HOME/.local/bin/nomarh-ops" "$@"
