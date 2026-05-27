#!/bin/bash
set -euo pipefail

mkdir -p "$HOME/projects"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is not installed yet; project bootstrap will run after gh is available."
  exit 0
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run 'gh auth login' inside the workspace, then rerun this script."
  exit 0
fi

repos=(
  100sats-seedlist-checker
  DockFolders
  Skill-obsidian
  ai-dev
  antelok-collector-facebook
  antelok
  antelok-media-worker
  bmu-info
  bmu.ro
  can-workbench
  discord-bot
  folieprotectie
  gande
  gsd-control
  hunting-season
  hunting-season-codex
  iron
  lajan
  obsidian-gsd-control
  og-bmu-one
  ore
  seed-checker
  website
)

for repo in "${repos[@]}"; do
  target="$HOME/projects/$repo"
  if [ -d "$target/.git" ]; then
    echo "[ok] $repo already cloned"
    continue
  fi
  owner="cansitki"
  case "$repo" in
    antelok-collector-facebook|antelok-media-worker)
      owner="antelokhq"
      ;;
  esac
  echo "[clone] $owner/$repo"
  gh repo clone "$owner/$repo" "$target" || echo "[warn] could not clone $owner/$repo"
done

if [ ! -d "$HOME/Can/.git" ] && gh repo view cansitki/vault >/dev/null 2>&1; then
  echo "[clone] cansitki/vault -> ~/Can"
  gh repo clone cansitki/vault "$HOME/Can" || true
fi

if [ -d "$HOME/vault" ] && [ ! -d "$HOME/vault/.git" ] && [ -z "$(find "$HOME/vault" -mindepth 1 -maxdepth 1 2>/dev/null)" ]; then
  rmdir "$HOME/vault"
fi

if [ ! -e "$HOME/vault" ] && [ -d "$HOME/Can" ]; then
  ln -s "$HOME/Can" "$HOME/vault"
fi
