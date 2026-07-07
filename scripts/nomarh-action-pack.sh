#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-action-pack.py" "$HOME/.local/bin/nomarh-action-pack"
"$HOME/.local/bin/nomarh-action-pack" "$@"
