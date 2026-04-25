#!/bin/bash
set -e

# One-time initialization
if [ ! -f ~/.workspace_initialized ]; then
  echo "First-time workspace setup..."

  # Create directory structure
  mkdir -p ~/projects ~/bin ~/.config ~/.local/bin

  # Setup git aliases
  git config --global alias.st status
  git config --global alias.co checkout
  git config --global alias.br branch
  git config --global alias.cm commit
  git config --global alias.lg "log --graph --pretty=format:'%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset' --abbrev-commit"

  # Clone dotfiles if specified
  %{if dotfiles_uri != ""}
  if [ ! -d ~/.dotfiles ]; then
    echo "Cloning dotfiles..."
    git clone ${dotfiles_uri} ~/.dotfiles && cd ~/.dotfiles && ./install.sh || true
  fi
  %{endif}

  # Create workspace README
  if [ ! -f ~/README.md ]; then
    cat > ~/README.md << 'EOFREADME'
# ${workspace_name}

## Quick Start Guide

### AI-Assisted Development
- **Claude Code**: `claude` in terminal or use the web app
- **OpenCode**: `opencode` in terminal or use the web UI
- **Pi**: `pi` in terminal
- **GSD (Claude/OpenCode)**: `/gsd:help` inside Claude Code or OpenCode
- **GSD (Pi)**: `/gsd help` inside Pi

### Available Tools & Versions
- **Node.js**: v24 (default), also available: 18, 20, 22
- **Package Managers**: PNPM, Yarn, Bun
- **Docker & Docker Compose**: Latest
- **Foundry**: Ethereum development toolkit
- **act**: Run GitHub Actions locally

### Shell
- **ZSH** with Starship prompt
- **tmux** for session persistence
- **direnv** for per-project env management

### Useful Commands

```bash
# AI Agents
claude                       # Start Claude Code
opencode                     # Start OpenCode
pi                           # Start Pi coding agent

# Docker
docker ps                    # List running containers
docker-compose up -d         # Start services

# Node.js
node --version               # Check Node version
pnpm install                 # Install with PNPM
yarn install                 # Install with Yarn
bun install                  # Install with Bun

# Git
gs                           # git status
gco -b feature/new           # Create branch
gc -m "message"              # Commit
git lg                       # Pretty log
```

### Workspace Info
- **Owner**: ${owner_name}
- **Email**: ${owner_email}
- **Created**: $(date)
EOFREADME
  fi

  # Mark as initialized
  touch ~/.workspace_initialized
  echo "Workspace initialized"
fi

# Ensure tools are on PATH (prepend without overriding agent PATH)
export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$HOME/.local/share/pnpm:$HOME/.bun/bin:$HOME/.foundry/bin:$PATH"

# Per-start initialization
echo "Starting workspace services..."

# Verify Docker access
if docker info &> /dev/null; then
  echo "Docker is accessible"
else
  echo "Warning: Docker is not accessible. Check socket mount."
fi

echo ""
echo "Workspace is ready!"
echo "Check ~/README.md for quick start guide"
echo ""

# Obsidian vault + CLI setup
# Vault is mounted at ~/vault via Docker volume (same uid 1000, no permission issues)
# CLI wrapper and socket are also mounted from host
if [ -d ~/vault ]; then
  echo "Obsidian vault mounted at ~/vault"

  # Symlink CLAUDE.md from vault so Claude Code loads brain rules
  mkdir -p ~/.claude
  if [ ! -f ~/.claude/settings.json ]; then
    echo '{}' > ~/.claude/settings.json
  fi
  if [ -f ~/vault/CLAUDE.md ]; then
    ln -sf ~/vault/CLAUDE.md ~/.claude/CLAUDE.md
    echo "CLAUDE.md symlinked from vault"
  fi

  echo "Obsidian CLI available at /usr/local/bin/obsidian"
else
  echo "WARNING: Vault not mounted. Add vault volume to workspace template."
fi
