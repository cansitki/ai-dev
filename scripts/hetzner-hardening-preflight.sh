#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/hetzner-hardening-preflight.py" "$HOME/.local/bin/hetzner-hardening-preflight"
"$HOME/.local/bin/hetzner-hardening-preflight" "$@"
