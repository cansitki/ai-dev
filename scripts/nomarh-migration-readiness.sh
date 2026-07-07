#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-migration-readiness.py" "$HOME/.local/bin/nomarh-migration-readiness"
"$HOME/.local/bin/nomarh-migration-readiness" "$@"
