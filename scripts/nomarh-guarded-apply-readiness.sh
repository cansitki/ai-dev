#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/nomarh-guarded-apply-readiness.py" "$HOME/.local/bin/nomarh-guarded-apply-readiness"
"$HOME/.local/bin/nomarh-guarded-apply-readiness" "$@"
