#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-vm-structure-map.py" "$HOME/.local/bin/nomarh-vm-structure-map"
"$HOME/.local/bin/nomarh-vm-structure-map" "$@"
