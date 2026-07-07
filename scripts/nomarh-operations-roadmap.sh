#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-operations-roadmap.py" "$HOME/.local/bin/nomarh-operations-roadmap"
"$HOME/.local/bin/nomarh-operations-roadmap" "$@"
