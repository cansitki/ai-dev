#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-migration-state-manifest.py" "$HOME/.local/bin/nomarh-migration-state-manifest"
"$HOME/.local/bin/nomarh-migration-state-manifest" "$@"
