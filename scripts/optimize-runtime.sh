#!/bin/bash
# Runtime optimizations for long-running workspaces.
#
# - Cap package caches (npm/pnpm/bun/pip) so they don't grow unbounded
# - Logrotate for Obsidian + VNC logs
# - Disable native postgres-16 service (we run Postgres via Docker for Supabase)
# - Weekly cleanup cron for cache items older than 30 days

set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
NC='\033[0m'

# --- Cache size caps ---
# npm: 2GB max, prune older entries beyond that
mkdir -p "$HOME/.npm"
if command -v npm >/dev/null 2>&1; then
    npm config set cache-max 2147483648 2>/dev/null || true   # 2 GB
    npm config set cache-min 86400 2>/dev/null || true        # keep last 24h hot
fi

# pnpm: store size cap via .npmrc
mkdir -p "$HOME/.config/pnpm"
if ! grep -q "store-prune" "$HOME/.npmrc" 2>/dev/null; then
    echo "store-prune=true" >> "$HOME/.npmrc"
fi

# pip: cap to 2GB by purging excess on each session start
if command -v pip >/dev/null 2>&1; then
    PIP_CACHE_DIR="$HOME/.cache/pip"
    if [ -d "$PIP_CACHE_DIR" ]; then
        SIZE_KB=$(du -sk "$PIP_CACHE_DIR" 2>/dev/null | cut -f1 || echo 0)
        if [ "$SIZE_KB" -gt 2097152 ]; then  # > 2 GB
            echo "pip cache exceeds 2GB, purging..."
            pip cache purge >/dev/null 2>&1 || true
        fi
    fi
fi

# bun: prune cache to 2GB
if command -v bun >/dev/null 2>&1; then
    BUN_CACHE="$HOME/.bun/install/cache"
    if [ -d "$BUN_CACHE" ]; then
        SIZE_KB=$(du -sk "$BUN_CACHE" 2>/dev/null | cut -f1 || echo 0)
        if [ "$SIZE_KB" -gt 2097152 ]; then
            echo "bun cache exceeds 2GB, pruning..."
            bun pm cache rm 2>/dev/null || true
        fi
    fi
fi

# --- Disable native postgres (we use Docker postgres for Supabase) ---
if systemctl list-unit-files 2>/dev/null | grep -q postgresql; then
    sudo systemctl disable --now postgresql 2>/dev/null || true
fi

# --- Logrotate config for Obsidian + VNC logs ---
sudo tee /etc/logrotate.d/coder-workspace > /dev/null <<EOF
/home/coder/.config/obsidian/*.log {
    weekly
    rotate 4
    missingok
    compress
    notifempty
    copytruncate
}
EOF

# --- Weekly cleanup cron — purge cache items older than 30 days ---
CRON_LINE='0 3 * * 0 find $HOME/.cache -type f -atime +30 -delete 2>/dev/null; find $HOME/.cache -type d -empty -delete 2>/dev/null'
( crontab -l 2>/dev/null | grep -v "find.*\.cache.*atime"; echo "$CRON_LINE" ) | crontab - 2>/dev/null || true

echo -e "${GREEN}Runtime optimizations applied${NC}"
