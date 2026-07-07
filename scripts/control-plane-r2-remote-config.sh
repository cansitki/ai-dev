#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/control-plane-r2-remote-config.py" "$HOME/.local/bin/control-plane-r2-remote-config"
"$HOME/.local/bin/control-plane-r2-remote-config" "$@"
