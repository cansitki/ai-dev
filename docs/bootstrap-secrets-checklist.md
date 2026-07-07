# VM Bootstrap Secrets Checklist

This is the pre-launch checklist for a fresh `ai-dev` workspace. Do not commit
real secret values. Put values into the Coder launch form, a private secret
manager, or a local `.env` file after the workspace is created.

## Required Before Launch

These are the secrets/configs that make the current VM come up ready instead of
half-configured.

| Area | Coder launch parameter | Runtime env/file | Why it is needed |
| --- | --- | --- | --- |
| GitHub | `github_token` | `GITHUB_TOKEN`, `GH_TOKEN` | `gh` login, private repo clone/push, vault GitHub backup |
| Claude/Anthropic | `claude_code_api_key` | `ANTHROPIC_API_KEY` | Claude Code |
| Codex/OpenAI | `openai_api_key` | `OPENAI_API_KEY` | Codex/OpenAI-backed tools |
| Obsidian Remotely Save | `remotely_save_s3_access_key_id` | `REMOTELY_SAVE_S3_ACCESS_KEY_ID` | Remotely Save S3 access key |
| Obsidian Remotely Save | `remotely_save_s3_secret_access_key` | `REMOTELY_SAVE_S3_SECRET_ACCESS_KEY` | Remotely Save S3 secret key |
| Obsidian Remotely Save | `remotely_save_s3_bucket` | `REMOTELY_SAVE_S3_BUCKET` | Remotely Save bucket |
| Obsidian Remotely Save | `remotely_save_s3_endpoint` | `REMOTELY_SAVE_S3_ENDPOINT` | Remotely Save endpoint |
| Obsidian Remotely Save | `remotely_save_s3_region` | `REMOTELY_SAVE_S3_REGION` | Remotely Save region, usually `auto` for R2 |
| Obsidian Remotely Save | `remotely_save_remote_prefix` | `REMOTELY_SAVE_REMOTE_PREFIX` | Optional Remotely Save remote prefix |
| Cloudflare | `cloudflare_api_token` | `CLOUDFLARE_API_TOKEN` | tunnels, DNS, workers, migrations |
| Cloudflare | `cloudflare_account_id` | `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account-level automation |
| Cloudflare | `cloudflare_zone_id` | `CLOUDFLARE_ZONE_ID` | DNS/zone automation |
| Theme service | `cloudflare_kv_theme_namespace_id` | `CLOUDFLARE_KV_THEME_NAMESPACE_ID` | tmux theme sync worker KV |
| Theme service | `tmux_theme_sync_url` | `TMUX_THEME_SYNC_URL` | theme sync Worker URL |
| Theme service | `tmux_theme_sync_enabled` | `TMUX_THEME_SYNC_ENABLED` | whether sync auto-starts when a token exists |
| Theme service | `tmux_theme_sync_token` | `TMUX_THEME_SYNC_TOKEN` | theme sync auth |
| Email tooling | `resend_api_key` | `RESEND_API_KEY` | Resend email tests/tools |
| Email tooling | `mailgun_api_key` | `MAILGUN_API_KEY` | Mailgun email tests/tools |
| Email/AWS tooling | `aws_access_key_id` | `AWS_ACCESS_KEY_ID` | AWS/SES/S3 tooling |
| Email/AWS tooling | `aws_secret_access_key` | `AWS_SECRET_ACCESS_KEY` | AWS/SES/S3 tooling |

Project `.env.example` files can define extra per-project keys such as
Supabase, Stripe, Sentry, Inngest, Google, Meta, Apify, Eulerstream, chain RPC
URLs, and R2 project buckets. These are not core VM bootstrap blockers; add
them only when that project is being launched.

## Current VM Inventory

This inventory was created from config file names, env variable names, tmux
sessions, and plugin settings. No secret values were copied here.

| Current path/session | What it contains |
| --- | --- |
| `~/Can/.obsidian/plugins/remotely-save/data.json` | Remotely Save S3 config is present; service type is S3 and official Obsidian Sync is disabled |
| `vault-backup` tmux session | GitHub-backed vault backup loop |
| `~/.config/gh/hosts.yml` | GitHub CLI auth for private repos and vault backup |
| `~/.codex/auth.json` | Codex/OpenAI auth material |
| `~/.cloudflare-secure/bmu-migration.env` | Cloudflare API token for migration/infra work |
| `~/main.env` | VM domain, Cloudflare, tunnel, theme, and workspace defaults |
| `~/email-test/.env` | Resend, Mailgun, AWS email test credentials |

## What The Template Now Does

- Prompts for the core VM tokens/configs as masked Coder launch parameters.
- Exports the provided values into the workspace process environment.
- Installs `tmux-theme`, `tmux-theme-sync-poll`, and `tmux-theme-sync-start`.
  The poller starts when `tmux_theme_sync_url` and `tmux_theme_sync_token` are
  present and `tmux_theme_sync_enabled` is true. Use `tmux-theme-sync-disable`
  or alias `tsync-off` for a workspace that should not follow the shared theme.
- Installs the Nomarh daily operations CLI set into `~/.local/bin`, including
  `nomarh-ops`, `can-doctor`, backup/restore gates, mail gate, tmux cleanup,
  migration checks, guarded action tools, and `can-morning` as the one-command
  daily start.
- Installs and runs `vault-guard` on startup. Startup scan is report-only; use
  `vault-guard quarantine` manually to move quarantinable raw/code files to
  `~/vault-quarantine/`.
- Installs and runs `can-doctor` on startup for a no-secrets health check of the
  vault, Obsidian sync mode, Remotely Save, backup loops, tmux services, GitHub
  auth, and migration readiness.
- Authenticates `gh` from `GH_TOKEN`/`GITHUB_TOKEN` without printing the token.

## Security Caveat

Masked Coder launch parameters hide token entry in the UI, but they are still
passed into Terraform and the workspace environment. Treat Coder and Terraform
state as sensitive infrastructure. If a token should never persist in Coder,
make that parameter ephemeral and be prepared to re-enter it on future starts.

## Still Manual / One-Time

- Obsidian Remotely Save plugin settings live in plugin JSON. The template
  prompts for the values and exports them, but the plugin may still need a
  one-time import/write step inside Obsidian if a fresh vault has no
  `remotely-save/data.json`.
- Existing project databases are runtime state. Back them up/restore them
  separately from API tokens.

## Operational Commands

```bash
can-morning
can-doctor
nomarh-operator-card --refresh
nomarh-ops --refresh
tmux-theme status
vault-guard scan
vault-guard quarantine
```

`vault-guard scan` never deletes or moves files. `vault-guard quarantine` moves
only quarantinable suspicious paths outside the vault and preserves relative
paths under `~/vault-quarantine/<timestamp>/`.
