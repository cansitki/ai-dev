# AI Development Coder Template

A lean Coder template for Nomarh development workspaces. It keeps the tools we actually use: Claude Code, Codex CLI support, Docker, Node.js, GitHub CLI, tmux, and Obsidian Desktop through noVNC.

## Features

### AI-Assisted Development

- **Claude Code** - Anthropic coding agent with CLI and Coder app access
- **Codex usage guard** - Local usage guard for unattended Codex runs using Codex session telemetry
- **OpenAI/Codex env support** - `OPENAI_API_KEY` can be supplied through template parameters
- **Tmux/Codex theme sync** - Starts safely in dark mode, repairs Codex theme state on workspace startup, and optionally follows the Mac light/dark mode through `cansitki/tmux-theme-sync`

### Development Environment

- **Docker** - Docker + Compose access through the mounted host socket
- **Node.js** - Multiple versions via the Node version switcher
- **Package managers** - PNPM, Yarn, and Bun
- **GitHub CLI** - Auth support through the configured GitHub token/external auth flow
- **ZSH** - Oh My Zsh with Starship prompt, autosuggestions, and syntax highlighting
- **tmux** - Persistent terminal sessions for long-running work
- **direnv** - Per-project environment management
- **Obsidian Desktop** - Workspace-local desktop app exposed through noVNC
- **Nomarh ops toolkit** - Installs `nomarh-ops`, `can-doctor`, backup gates, mail gate, migration checks, tmux cleanup review, and daily ops commands
- **Morning command** - `can-morning` refreshes the operating picture and prints the operator card, ops brief, and migration readiness

### Reliability

- **Resource limits** - 24 GB RAM, 6 CPU cores, 48 GB total memory with swap
- **Health checks** - Container health monitoring
- **Monitoring apps** - CPU, RAM, disk, and swap history launchers
- **Persistent volume** - Home directory survives workspace restarts
- **Vault backup** - Optional vault GitHub backup loop

## Quick Start

### Prerequisites

- Coder v2.x deployed and running
- Docker available on the Coder host
- GitHub external auth configured when private repo access is needed

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
codex-usage-guard status  # Codex usage guard
tmux-theme status         # Current tmux/Codex theme mode
nomarh-operator-card --refresh # Compact daily operator view
can-morning              # One-command daily start
nomarh-ops --refresh      # Daily ops view
docker ps                 # Docker access
node --version            # Node.js
bun --version             # Bun
yarn --version            # Yarn
gh auth status            # GitHub CLI
starship --version        # Starship prompt
```

## Configuration

### Template Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `docker_socket` | `""` | Custom Docker socket URI |
| `dotfiles_uri` | `""` | Git URI for dotfiles repository |
| `claude_code_model` | `""` | Default model for Claude Code |
| `claude_code_api_key` | `""` | Anthropic API key |
| `claude_code_system_prompt` | `""` | Custom system prompt |
| `claude_code_allowed_tools` | `""` | Comma-separated allowed tools |
| `github_token` | `""` | GitHub token for CLI/private repos/vault backup |
| `openai_api_key` | `""` | OpenAI API key for Codex/OpenAI-backed tools |
| `cloudflare_api_token` | `""` | Cloudflare API token for Cloudflare automation |
| `tmux_theme_sync_url` | `https://theme.nomarh.com` | Worker URL used by tmux/Codex theme sync |
| `tmux_theme_sync_enabled` | `true` | Auto-start theme sync when a token is configured |
| `tmux_theme_sync_token` | `""` | Shared token for theme sync polling |
| `remotely_save_s3_*` | `""` | Obsidian Remotely Save S3/R2 configuration |

### Resource Limits

Default container limits are defined in `main.tf`:

```hcl
memory      = 24576
memory_swap = 49152
cpu_shares  = 6144
```

## Architecture

```text
+---------------------------------------------+
|   Coder Workspace Container                  |
|                                             |
|  +----------------------------------------+ |
|  |  AI Tools                              | |
|  |  - Claude Code                         | |
|  |  - Codex usage guard                   | |
|  +----------------------------------------+ |
|                                             |
|  +----------------------------------------+ |
|  |  User Environment                      | |
|  |  - ZSH + Oh My Zsh + Starship          | |
|  |  - Node.js + PNPM/Yarn/Bun             | |
|  |  - tmux + direnv                       | |
|  +----------------------------------------+ |
|                                             |
|  +----------------------------------------+ |
|  |  Services                              | |
|  |  - Obsidian Desktop + noVNC            | |
|  |  - Tmux browser picker                 | |
|  |  - Nomarh ops toolkit                  | |
|  |  - Tmux/Codex theme sync               | |
|  +----------------------------------------+ |
|                                             |
|  +------------------+                       |
|  |  Docker Socket   |                       |
|  +------------------+                       |
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
| Claude Code | Terminal app | Claude Code in a terminal window |
| Nomarh Operator | Terminal app | Runs `can-morning` and opens a shell |
| Obsidian VNC | Path app (`:6080`) | noVNC access to workspace-local Obsidian Desktop |
| Tmux | Path app (`:7681`) | Browser-accessible tmux session picker |
| sar CPU | Terminal app | Historical CPU usage from sysstat |
| sar RAM | Terminal app | Historical memory usage from sysstat |

## Troubleshooting

### AI tool not found after startup

Tools are installed during the build/start scripts. Check the script logs in the Coder UI under the workspace build logs.

```bash
source ~/.zshrc
node --version
claude --version
codex-usage-guard status
```

### Theme sync is not following the Mac

```bash
tmux-theme status
tmux-theme check dark || tmux-theme dark
tmux ls | grep tmux-theme-sync
tmux-theme-sync-start
```

The poller starts only when `tmux_theme_sync_token` is provided and `tmux_theme_sync_enabled` is true. The token is written to `~/.config/tmux-theme-sync/env` with `0600` permissions.
If a later template start receives an empty token, it preserves the existing nonempty token instead of disabling a working sync installation. Missing or invalid `~/.codex/tmux-theme` state defaults to `dark`; every workspace start atomically persists that state, reapplies terminal colors, and repairs `[tui].theme` in `~/.codex/config.toml`.
When the optional Codex theme manager is installed, startup also asks its guard to repair the pinned dark state and managed `~/.local/bin/codex` wrapper, then validates the active release. Guard failures emit a warning but do not block workspace startup.
The poller also runs the repair when the remote mode already matches the local state, and its tmux session is marked with `@nomarh_scope=system` so normal project session views can hide it.
The installed runtime also writes `~/.config/tmux-theme-sync/source`; current baseline is `cansitki/tmux-theme-sync` commit `be7cae0`, including the fail-closed patched Codex release manager and the template hardening for Coder startup behavior.

Useful aliases:

```bash
tlight
tdark
tsync-on
tsync-off
codex-theme status
```

`tlist` remains reserved for the Nomarh tmux session picker; theme controls do not replace it with an alias.

`tsync-off` writes `~/.config/tmux-theme-sync/disabled` and stops local polling, so one workspace can stay light/dark manually while other workspaces continue following the shared Worker.

### Coder warns about wildcard app URLs

This template intentionally uses path-routed apps for Obsidian VNC and tmux, so it does not require Coder `--wildcard-access-url` on `coder.nomarh.com`. Do not re-add subdomain-only apps unless wildcard routing is configured on the Coder server.

### Daily ops view is stale

```bash
can-morning
nomarh-ops --refresh
operator
ops-card
ops-summary
can-ops-scheduler status
can-ops-scheduler start
```

### Docker not accessible

```bash
ls -l /var/run/docker.sock
groups | grep docker
docker info
```

### Guard unattended Codex usage

```bash
codex-usage-guard status
codex-usage-guard start --name sleep --max-weekly-delta-percent 10
codex-usage-guard check --name sleep
codex-usage-guard run --name sleep -- codex exec "continue the current task"
```

Run `codex-usage-guard check --name sleep` before loop iterations, or wrap worker launches with `codex-usage-guard run --name sleep -- ...`. A non-zero exit means the worker should stop starting new Codex work and leave durable handoff files.

### Obsidian CLI cannot find Obsidian

The Coder script `scripts/obsidian-serve.sh` starts the Desktop app with `/opt/Obsidian/obsidian`. It runs a Desktop watchdog in tmux session `obsidian-headless`, opens the workspace vault at `~/Can`, restarts Desktop if it exits, and keeps `~/vault` as a compatibility symlink.

```bash
./scripts/obsidian-serve.sh
tmux ls | grep obsidian-headless
obsidian read file="Vault Index"
```

## Security

- Docker socket is mounted, so users have Docker access on the host daemon.
- API keys are marked as sensitive in Terraform and should not appear in plan output.
- Use this template only in trusted development environments.
- Review template access controls in Coder admin.

## External Resources

- [Coder Documentation](https://coder.com/docs)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [Starship Prompt](https://starship.rs)
