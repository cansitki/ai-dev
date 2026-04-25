# AI-Assisted Full-Stack Development - Coder Template

A production-ready Coder template for AI-assisted full-stack development. Features three AI coding agents (Claude Code, OpenCode, Pi), comprehensive tooling, Docker, Node.js, Foundry, and everything you need for modern development.

## Features

### AI-Assisted Development
- **Claude Code** - Anthropic's coding agent with CLI and web interface
- **OpenCode** - Open-source AI coding assistant with CLI and web UI
- **Pi** - Minimal terminal coding agent with extension support
- **GSD (get-shit-done)** - Meta-prompting system for Claude Code and OpenCode
- **GSD-2** - Autonomous development agent for Pi
- All AI tools are configurable via template variables

### Development Environment
- **Docker** - Full Docker + Compose + act (run GitHub Actions locally)
- **Node.js** - Multiple versions (18, 20, 22, 24) via version switcher
- **Package Managers** - PNPM, Yarn, and Bun
- **Foundry** - Complete Ethereum development toolkit
- **Git** - Latest version with productivity aliases
- **GitHub CLI** - Pre-authenticated via Coder external auth
- **ZSH** - Oh My Zsh with Starship prompt, autosuggestions, and syntax highlighting
- **tmux** - Session persistence for long-running agent sessions
- **direnv** - Per-project environment management

### VS Code Integration
- 20 curated extensions including Solidity, Tailwind CSS, GraphQL, Prisma, GitLens, Docker, Error Lens, and more
- Pre-configured settings for formatting, themes, and terminal

### Performance & Reliability
- **Resource limits** - 12GB RAM, 6 CPU cores, 32GB total memory (with swap)
- **Health checks** - Automatic container health monitoring
- **Monitoring** - Built-in CPU, RAM, disk, and swap metrics
- **Persistent volume** - Home directory survives workspace restarts

## Quick Start

### Prerequisites
- Coder v2.x deployed and running
- Docker available on Coder host
- GitHub external auth configured (id: `primary-github`)

### Installation

```bash
git clone <this-repo>
cd ai-dev
coder templates push ai-dev
```

### Create a Workspace

```bash
coder create --template ai-dev my-workspace
coder ssh my-workspace
```

### Verify

```bash
claude --version          # Claude Code
opencode --version        # OpenCode
pi --version              # Pi coding agent
docker ps                 # Docker access
node --version            # Node.js
bun --version             # Bun
yarn --version            # Yarn
forge --version           # Foundry
gh auth status            # GitHub CLI
starship --version        # Starship prompt
```

## Configuration

### Template Variables

All AI tools can be configured when creating or updating a workspace:

| Variable | Default | Description |
|----------|---------|-------------|
| `docker_socket` | `""` | Custom Docker socket URI |
| `dotfiles_uri` | `""` | Git URI for dotfiles repository |
| `opencode_model` | `anthropic/claude-opus-4-6` | Default model for OpenCode |
| `opencode_config_json` | `""` | Full OpenCode config JSON override |
| `claude_code_model` | `""` | Default model for Claude Code |
| `claude_code_api_key` | `""` | Anthropic API key (sensitive) |
| `claude_code_system_prompt` | `""` | Custom system prompt |
| `claude_code_allowed_tools` | `""` | Comma-separated allowed tools |
| `pi_api_key` | `""` | API key for Pi's LLM provider (sensitive) |
| `pi_model` | `claude-opus-4-6` | Model for Pi |
| `pi_provider` | `anthropic` | LLM provider for Pi |

### Resource Limits

Default container limits (edit `main.tf` to change):

```hcl
memory      = 12288   # 12GB RAM (in MiB)
memory_swap = 32768   # 32GB total (RAM + swap, in MiB)
cpu_shares  = 6144    # 6 CPU cores (relative weight)
```

## Architecture

```
+---------------------------------------------+
|   Coder Workspace Container                  |
|                                              |
|  +----------------------------------------+  |
|  |  AI Agents                             |  |
|  |  - Claude Code (CLI + web)             |  |
|  |  - OpenCode (CLI + web UI :62748)      |  |
|  |  - Pi (terminal)                       |  |
|  |  - GSD / GSD-2 (slash commands)        |  |
|  +----------------------------------------+  |
|                                              |
|  +----------------------------------------+  |
|  |  User Environment                      |  |
|  |  - ZSH + Oh My Zsh + Starship         |  |
|  |  - Node.js + PNPM/Yarn/Bun            |  |
|  |  - Foundry + Solidity                  |  |
|  |  - tmux + direnv                       |  |
|  +----------------------------------------+  |
|                                              |
|  +----------------------------------------+  |
|  |  Services                              |  |
|  |  - VS Code Server                      |  |
|  |  - File Browser                        |  |
|  +----------------------------------------+  |
|                                              |
|  +------------------+                        |
|  |  Docker Socket   |                        |
|  +------------------+                        |
+---------------------------------------------+
           |
           v
    +--------------+
    |  Host Docker |
    |  Daemon      |
    +--------------+
```

## Accessible Apps

| App | Access | Description |
|-----|--------|-------------|
| VS Code | Subdomain | Full IDE with extensions |
| OpenCode UI | Subdomain (`:62748`) | Web interface for OpenCode |
| Claude Code | Web app via module | Claude Code web interface |
| Pi Agent | Terminal app | Pi in a terminal window |
| File Browser | Subdomain | Web-based file management |

## Troubleshooting

### AI tool not found after startup
Tools are installed during the development tools script. Check the script logs in Coder UI under the workspace's build logs. If npm-based tools fail, ensure Node.js is available:
```bash
source ~/.zshrc
node --version
npm install -g @mariozechner/pi-coding-agent
```

### Docker not accessible
```bash
ls -l /var/run/docker.sock
groups | grep docker
docker info
```

### GSD commands not available
```bash
# Reinstall for Claude Code + OpenCode
npx get-shit-done-cc@latest --claude --opencode --global

# Reinstall for Pi
npm install -g gsd-pi
```

## Security

- Docker socket is mounted — users have full Docker access on the host daemon
- API keys are marked as sensitive in Terraform and won't appear in plan output
- Use in trusted development environments
- Review template access controls in Coder admin

## External Resources

- [Coder Documentation](https://coder.com/docs)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [OpenCode](https://opencode.ai)
- [Pi Coding Agent](https://github.com/badlogic/pi-mono)
- [GSD (get-shit-done)](https://github.com/gsd-build/get-shit-done)
- [GSD-2](https://github.com/gsd-build/gsd-2)
- [Starship Prompt](https://starship.rs)
- [Foundry Book](https://book.getfoundry.sh)
