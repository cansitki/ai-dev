#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-ops-evidence-digest.py" "$HOME/.local/bin/nomarh-ops-evidence-digest"
"$HOME/.local/bin/nomarh-ops-evidence-digest" "$@"
