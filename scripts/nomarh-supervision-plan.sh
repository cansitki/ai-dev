#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-supervision-plan.py" "$HOME/.local/bin/nomarh-supervision-plan"
"$HOME/.local/bin/nomarh-supervision-plan" "$@"
