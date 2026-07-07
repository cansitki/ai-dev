#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/hetzner-access-preflight.py" "$HOME/.local/bin/hetzner-access-preflight"
"$HOME/.local/bin/hetzner-access-preflight" "$@"
