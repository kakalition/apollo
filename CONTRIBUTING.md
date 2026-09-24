# Contributing

Thanks for your interest in Apollo. This is a focused, single-user project, so the
contribution surface is deliberately small — high-signal bug reports and focused pull
requests are very welcome.

## Ground rules

- Keep Apollo **local-first** and **single-user**. Multi-tenancy, auth, and a web UI
  are out of scope.
- Prefer config over hard-coded integrations (MCP servers, model tiers, skills).
- No arbitrary shell execution.
- Every mutation must go through a repository so it is audited and emitted to the
  transactional outbox.

## Development setup

```bash
uv sync --extra memory        # add --extra voice / --extra local-embeddings if needed
cp .env.example .env          # fill in provider + Telegram keys
uv run apollo init-db
uv run apollo doctor
```

## Before you open a PR

Run the full gate and make sure it is green:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

- New behaviour needs a test. Pure logic goes in `tests/unit`, cross-process flows in
  `tests/integration`, model-quality questions in `tests/evals`.
- Schema changes require an Alembic migration (`uv run alembic revision --autogenerate`).
- Never commit real secrets. `.env` is git-ignored; use `.env.example` for new keys.

## Commit style

Short imperative subject lines, e.g. `queue: requeue expired leases on startup`.
Reference the milestone or subsystem when useful.

## Skills

A pure-prompt skill is a single `skills/<slug>/SKILL.md`; Python-backed skills add a
`tools.py` with `register(registry)`. See [`docs/FEATURES.md`](docs/FEATURES.md) §4.K.
