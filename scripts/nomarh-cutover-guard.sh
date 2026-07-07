#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-cutover-guard.py" "$HOME/.local/bin/nomarh-cutover-guard"
"$HOME/.local/bin/nomarh-cutover-guard" "$@"
