#!/usr/bin/env bash
set -euo pipefail

install -d "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/hetzner-hardening-remediation.py" "$HOME/.local/bin/hetzner-hardening-remediation"
"$HOME/.local/bin/hetzner-hardening-remediation" "$@"
