#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-secret-rotation-plan.py" "$HOME/.local/bin/nomarh-secret-rotation-plan"
"$HOME/.local/bin/nomarh-secret-rotation-plan" "$@"
