#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-guarded-action-audit.py" "$HOME/.local/bin/nomarh-guarded-action-audit"
"$HOME/.local/bin/nomarh-guarded-action-audit" "$@"
