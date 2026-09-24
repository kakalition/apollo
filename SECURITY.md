# Security Policy

Apollo is a **local-first, single-user** application. It has no multi-tenant
surface, no web server, and no authentication layer by design. Your data stays on
your machine; the only outbound traffic is to the model/embeddings provider,
Telegram, and MCP servers you explicitly configure.

## Reporting a vulnerability

Please open a private security advisory via **Security → Report a vulnerability** on
this repository, or email the maintainer. Do not open a public issue for a suspected
vulnerability. We aim to acknowledge reports within a few days.

## Handling secrets

- Secrets live in `.env` (mode `0600`), which is git-ignored along with `data/` and
  editor configs that may embed provider keys (e.g. `kilo.json`).
- Secrets are never logged; `Settings.redacted()` is used for any config dump.
- If you believe a key has been committed, rotate it immediately and purge it from
  git history — assume a pushed key is compromised.

## Threat model and mitigations

| Risk | Mitigation |
|---|---|
| Another Telegram user talks to the bot | Numeric user-id allowlist enforced on every update |
| Prompt injection via MCP/web/tool output | Tool output is untrusted data; the trust boundary is stated to every agent; write tiers gate mutations |
| Unintended destructive actions | `irreversible` actions require explicit approval and auto-deny on expiry; every mutation is audited |
| Filesystem escape | Vault access is path-sandboxed; no arbitrary shell execution exists in v1 |
| Secret leakage into logs | Secrets are redacted and never passed to loggers |
| Multi-process SQLite corruption/lost work | WAL, `BEGIN IMMEDIATE`, leases, and a transactional outbox |

## Supported versions

This is pre-1.0 software; only the `main` branch is supported.
