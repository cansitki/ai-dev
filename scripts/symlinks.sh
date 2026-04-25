#!/bin/bash
set -e

BOLD='\033[0;1m'
GREEN='\033[0;32m'
RESET='\033[0m'

printf "$${BOLD}Creating tool symlinks in ~/.local/bin...$${RESET}\n"
mkdir -p $HOME/.local/bin

# Node.js / npm / npx — from system install (NodeSource in Dockerfile)
for bin in node npm npx corepack; do
  SYS_BIN=$(command -v "$bin" 2>/dev/null)
  [ -n "$SYS_BIN" ] && ln -sf "$SYS_BIN" "$HOME/.local/bin/$bin"
done

# Symlink globally installed npm packages (pi, gsd, claude, etc.)
# The Coder nodejs module installs to /opt/node*/bin/, so check there too
NPM_GLOBAL_BIN=$(npm -g bin 2>/dev/null || echo "")
for bindir in $NPM_GLOBAL_BIN /usr/lib/node_modules/.bin /opt/node*/bin; do
  if [ -d "$bindir" ]; then
    for bin in "$bindir/"*; do
      [ -x "$bin" ] && [ ! -e "$HOME/.local/bin/$(basename "$bin")" ] && ln -sf "$bin" "$HOME/.local/bin/$(basename "$bin")"
    done
  fi
done
printf "$${GREEN}[ok] Node.js symlinked$${RESET}\n"

# PNPM
[ -f "$HOME/.local/share/pnpm/pnpm" ] && ln -sf "$HOME/.local/share/pnpm/pnpm" "$HOME/.local/bin/pnpm"
[ -f "$HOME/.local/share/pnpm/pnpx" ] && ln -sf "$HOME/.local/share/pnpm/pnpx" "$HOME/.local/bin/pnpx"

# Bun
[ -f "$HOME/.bun/bin/bun" ] && ln -sf "$HOME/.bun/bin/bun" "$HOME/.local/bin/bun"
[ -f "$HOME/.bun/bin/bunx" ] && ln -sf "$HOME/.bun/bin/bunx" "$HOME/.local/bin/bunx"

# Foundry
for bin in forge cast anvil chisel; do
  [ -f "$HOME/.foundry/bin/$bin" ] && ln -sf "$HOME/.foundry/bin/$bin" "$HOME/.local/bin/$bin"
done

# OpenCode
[ -f "$HOME/.opencode/bin/opencode" ] && ln -sf "$HOME/.opencode/bin/opencode" "$HOME/.local/bin/opencode"

# GSD (gsd-pi) — ensure gsd and gsd-cli are on PATH
for bin in gsd gsd-cli; do
  if [ ! -e "$HOME/.local/bin/$bin" ]; then
    GSD_BIN=$(command -v "$bin" 2>/dev/null || find /opt/node*/bin -name "$bin" 2>/dev/null | head -1)
    [ -n "$GSD_BIN" ] && ln -sf "$GSD_BIN" "$HOME/.local/bin/$bin"
  fi
done

printf "$${GREEN}[ok] All tool symlinks created$${RESET}\n"

echo ""
printf "$${GREEN}All development tools are ready!$${RESET}\n"
echo ""
