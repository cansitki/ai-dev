#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-service-migration-map.py" "$HOME/.local/bin/nomarh-service-migration-map"
"$HOME/.local/bin/nomarh-service-migration-map" "$@"
