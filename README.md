<div align="center">

<img src="assets/apollo-logo.png" alt="Apollo logo" width="148" />

# Apollo

**A single-user, local-first personal agent platform.**

Declare goals. Apollo decomposes them into practices, projects, habits and metrics,
a scheduler drives check-ins and reviews, and agents use skills and MCP tools to do
real work — while keeping you accountable.

[![CI](https://github.com/kakalition/apollo/actions/workflows/ci.yml/badge.svg)](https://github.com/kakalition/apollo/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e.svg)](LICENSE)
[![Pydantic AI](https://img.shields.io/badge/agents-Pydantic%20AI-e92063.svg)](https://ai.pydantic.dev/)
[![MCP](https://img.shields.io/badge/protocol-MCP-6e56cf.svg)](https://modelcontextprotocol.io/)
[![Local-first](https://img.shields.io/badge/local--first-yes-0ea5e9.svg)](#privacy--security)

**[Features & use cases](docs/FEATURES.md)** ·
**[Architecture](#architecture)** ·
**[Quick start](#quick-start)** ·
**[Configuration](#configuration)** ·
**[CLI](#cli-reference)**

</div>

---

## Why Apollo

Most productivity tools give you a place to put tasks. Apollo gives you a **loop**:
evidence feeds reviews, reviews rewrite practice, and agents do the upkeep.

- **Ontology, not tags.** A `Goal` is what you want; a `Practice` is what you run to
  get it. Projects, tasks, habits and metrics hang off those two — so the system knows
  *why* something matters, not just that it exists.
- **Agents with a job.** A cheap supervisor routes to specialists (triage, planner,
  coach, researcher) that capture, decompose, review and research. Every run is typed,
  logged and replayable.
- **A scheduler that acts.** Time, event and condition rules drive briefings, reviews,
  drift detection and overdue sweeps.
- **Durable memory.** Your journal, check-ins and reviews are embedded and recalled
  semantically, behind a swappable `Memory` facade.
- **Local-first.** Your database, vault and vector store stay on your machine. The only
  outbound traffic is your model/embeddings endpoint, Telegram, and MCP servers you
  choose to add.
- **Bidirectional MCP.** Apollo *consumes* external MCP servers as tools, and *exposes*
  itself to Claude Desktop, Kilo and Cursor as an MCP server.

## Features

| Area | What you get |
|---|---|
| **Domain** | Areas, Goals, Practices, Projects, Tasks, Habits, Metrics, Check-ins, Reviews, Journal — with a classification test that keeps the schema honest |
| **Agents** | Supervisor → triage / planner / coach / researcher; tiered models; typed outputs; per-run `RunLog`; streaming replies with Stop |
| **Skills** | Markdown-first (`SKILL.md`) with progressive disclosure, hot reload, and optional Python `tools.py` gated by `allowed-tools` |
| **Memory** | Mem0 over a local Chroma server, API embeddings with a configurable fallback chain, worker-only writes, rebuildable from the vault |
| **Scheduling** | Cron, event subscriptions and safe registered condition predicates; cooldowns, timezone-aware, quiet hours |
| **Telegram** | Native Bot API 10.3: streaming drafts, rich HTML, inline keyboards, approvals, polls, reactions, deep links, inline mode |
| **MCP** | Config-driven client registry (default-deny allowlists, namespacing) and a curated stdio server with approval-aware writes |
| **Safety** | Read free · mutate auto+audited · irreversible requires approval; single-user allowlist; path-sandboxed vault; no shell |
| **Ops** | `apollo doctor`, migrations, pause/resume kill switch, job queue inspection, structured logs, opt-in OTel/Logfire tracing |
| **Quality** | Ruff, Pyright, 98 tests, `pydantic-evals` suites, CI on every push |

## Architecture

Split processes, one SQLite database as the source of truth, and a transactional
outbox for every side effect.

```
                 ┌──────────────────────────────────────────────┐
                 │  SQLite (WAL)   data/apollo.db               │
                 │  domain · events(outbox) · jobs              │
                 │  pending_actions · notifications · audit     │
                 │  vault_fts (FTS5 index of markdown vault)    │
                 └──────────────────────────────────────────────┘
                   ▲         ▲          ▲          ▲         ▲
        writes     │         │          │          │         │
   ┌───────────────┴──┐ ┌────┴─────┐ ┌──┴───────┐ ┌┴─────────┴───┐
   │ apollo telegram  │ │apollo-   │ │apollo-   │ │ apollo-mcp  │
   │ long polling     │ │worker    │ │dispatcher│ │ stdio (per  │
   │ in→events/jobs   │ │agents    │ │tick →    │ │ MCP client) │
   │ out←notifications│ │skills    │ │jobs      │ │ read tools +│
   └──────────────────┘ │memory    │ │retries   │ │ approval-   │
                        └────┬─────┘ └──────────┘ │ aware writes│
                             │                    └─────────────┘
                     ┌───────┴────────┐     ┌──────────────────┐
                     │ Chroma (server)│     │ MCP client       │
                     │ localhost:8000 │     │ registry →       │
                     └────────────────┘     │ calendar/web/…   │
                                            └──────────────────┘
```

| Process | Command | Responsibility |
|---|---|---|
| Telegram bot | `apollo telegram` | Inbound messages → events/jobs; drains notifications; renders approvals |
| Worker | `apollo worker` | Claims jobs, runs agents/skills, owns Mem0 writes |
| Dispatcher | `apollo dispatcher` | Scheduler tick, event drain, condition predicates, retries |
| MCP server | `apollo mcp` | stdio server for Claude Desktop / Kilo / Cursor |
| CLI | `apollo …` | Admin, migrations, inspection, one-off runs |

**Concurrency discipline.** WAL + `busy_timeout`, every write in a short
`BEGIN IMMEDIATE` transaction, atomic job claim (`UPDATE … RETURNING`), leases with
heartbeat, exponential backoff to dead-letter, and a DB advisory lock enforcing a
single dispatcher. Side effects are never performed inside a transaction — domain
mutation and its outbox event commit together.

## Quick start

```bash
# 1. Install (Python 3.11+; 3.12 recommended)
uv sync --extra memory          # add --extra voice, --extra local-embeddings as needed

# 2. Configure
cp .env.example .env && chmod 600 .env   # provider key, model ids, Telegram token
$EDITOR apollo.toml                       # timezone, tiers, autonomy, MCP servers

# 3. Verify everything is reachable
uv run apollo doctor

# 4. Start the whole stack (Chroma + dispatcher + worker + Telegram)
scripts/run.sh start
```

That's it — `scripts/run.sh` is the single entrypoint. It installs dependencies if
needed, creates the database, starts Chroma and waits for it to be healthy, then
brings up the dispatcher, worker and Telegram bot, and reports status.

```text
scripts/run.sh              # start everything (idempotent)
scripts/run.sh status       # ●/○ for each component
scripts/run.sh logs worker  # tail a component log
scripts/run.sh stop         # stop everything
scripts/run.sh restart
```

Send the bot a message and talk normally: *"remind me to call the bank tomorrow"*,
*"log a 6 for sleep"*, *"what should I focus on today?"*

### Why Chroma runs as a server (not embedded)

Chroma's embedded mode (`PersistentClient(path=…)`) takes an **exclusive file lock
and is single-process only**. Apollo is deliberately split across processes that all
touch memory — `worker` (writes), `dispatcher`, and `mcp`/agents (reads) — so an
embedded store can't be shared. Chroma therefore runs as a local server on loopback,
and Mem0 connects over HTTP.

That is still local-first: the vector store never leaves your machine. `scripts/run.sh`
starts it for you with `uv run chroma run --path ./data/chroma --port 8000`
(version-matched to `uv.lock`); no container runtime is required. See
[`docs/FEATURES.md`](docs/FEATURES.md) for details.

## Configuration

Non-secret settings live in `apollo.toml`; secrets live in `.env` (0600, git-ignored).

```toml
[app]
timezone = "America/New_York"

[provider]
tiers = { triage = "…", plan = "…", coach = "…", research = "…" }

[autonomy]
default_tier = "mutate"
irreversible = ["vault.delete", "web.send", "calendar.delete_event"]

[telegram]
topic_routing = false        # single chat by default; topics are optional
quiet_hours = { start = "22:00", end = "07:00" }

[memory]
enabled = true
chroma_url = "http://localhost:8000"
```

```dotenv
APOLLO_PROVIDER__BASE_URL=https://openrouter.ai/api/v1
APOLLO_PROVIDER__API_KEY=…
APOLLO_PROVIDER__CHAT_MODEL_ID=deepseek/deepseek-v4-flash-0731
APOLLO_PROVIDER__LIGHT_MODEL_ID=openai/gpt-oss-20b
APOLLO_PROVIDER__EMBEDDING_MODEL_ID=openai/text-embedding-3-small
APOLLO_TELEGRAM__BOT_TOKEN=…
APOLLO_TELEGRAM__ALLOWED_USER_IDS=[123456789]
```

Any OpenAI-compatible endpoint works. `CHAT_MODEL_ID` overrides all tiers;
`LIGHT_MODEL_ID` handles the simple schemas only (supervisor routing, memory
extraction) — capture and planning stay on the chat model because the large command
union is unreliable on tiny models. `EMBEDDING_MODEL_ID` overrides
`[embeddings].model`. If a provider serves no embeddings, Apollo falls back to a
second provider or local `fastembed`.

A typical capture (message → final Telegram reply) lands in **~6–10 s** end to end;
measure it with `uv run python scripts/bench_capture.py --count 3`.

## Telegram setup

Apollo ships in **single-chat mode**: natural language is routed by the supervisor,
so you just talk. Private-chat **topics** are optional (nine-topic information
architecture) — enable them in @BotFather **and** set `topic_routing = true`.

In **@BotFather**:

- `/mybots` → your bot → **Bot Settings** → **Topics in Private Chats** *(optional)*
- `/setinline` — enable inline mode (share your day from any chat)
- `/setdescription`, `/setabouttext`, `/setuserpic` — profile polish

Commands and the menu button are configured automatically at startup. `allowed_updates`
is set to `message, edited_message, callback_query, poll_answer, inline_query,
stopped_message_generation`.

## MCP

**Consume** external servers (default-deny — only allowlisted tools reach an agent,
namespaced):

```toml
[mcp.servers.calendar]
transport = "stdio"
command = ["npx", "-y", "@modelcontextprotocol/server-google-calendar"]
allowlist = ["list_events", "create_event"]
namespace = "calendar"
```

**Expose** Apollo to any MCP client:

```json
{ "mcpServers": { "apollo": { "command": "uv", "args": ["run", "apollo", "mcp"] } } }
```

Reads are free; writes return `applied` or `pending_approval`, and skills are exposed
as MCP prompts. See [`docs/FEATURES.md`](docs/FEATURES.md) for the full tool list.

## Skills

A skill is one markdown file with YAML frontmatter:

```markdown
---
name: weekly-review
description: Summarize practices, surface drift, propose adjustments.
triggers: ["schedule:weekly_review", "user:review", "event:review.due"]
allowed-tools: ["db.read", "db.write", "memory.recall", "notify.telegram"]
model-tier: coach
---
<instructions / methodology / output format>
```

The registry loads frontmatter only, keeping the supervisor prompt small; full
instructions load on demand. Optional `skills/<slug>/tools.py` adds Python tools.
Built-ins: `capture`, `daily-briefing`, `evening-checkin`, `weekly-review`,
`goal-decompose`, `drift-detect`, `deep-research`.

## Scheduling

Built-in routines: morning briefing 07:00 · evening check-in 21:00 · weekly review
Sun 18:00 · drift check daily · overdue sweep hourly · vault sync every 5 minutes.
Add your own with cron, event, or safe registered condition predicates
(`no_checkin_days`, `metric_below_target`, `habit_streak_broken`,
`goal_no_progress_days`, `overdue_tasks`). Quiet hours buffer non-urgent
notifications until the window ends.

## Privacy & security

- Everything local: SQLite, markdown vault and Chroma on loopback; single-user
  Telegram allowlist rejects everyone else.
- Autonomy tiers: `read` free · `mutate` auto-applied, audited and notified ·
  `irreversible` requires approval and auto-denies on expiry.
- Secrets are never logged; `.env`, `data/` and editor configs that may embed keys are
  git-ignored.
- MCP and web output is treated as untrusted data; the trust boundary is stated to
  every agent. No arbitrary shell execution in v1.

See [`SECURITY.md`](SECURITY.md) for the threat model and reporting process.

## CLI reference

```text
apollo version | doctor | init-db | upgrade | schema
apollo pause | resume | status
apollo worker [--once] | dispatcher [--once] | telegram | mcp
apollo run --agent <triage|planner|coach|researcher> "text"
apollo queue list|retry|replay|purge
apollo schedule list|toggle
apollo vault sync|search
apollo memory recall|reindex
apollo mcp-servers list|check
apollo topics list|reset
```

## Development

```bash
uv run ruff check .     # lint
uv run pyright          # types
uv run pytest           # unit + integration (98 tests)
uv run pytest -m eval   # evaluations (live model)
```

CI runs lint, types and tests on every push. Contributions are welcome — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Project layout

```text
apollo/
  apollo.toml  .env.example  pyproject.toml  alembic.ini
  assets/                    logo & brand assets
  docs/                      features & use cases
  scripts/                   run.sh (one-command stack), launchd/systemd templates
  skills/                    built-in skills (markdown + optional tools.py)
  src/apollo/
    domain/  db/  queue/  agents/  skills/  tools/
    mcp/  memory/  scheduler/  telegram/  observability/
  tests/                     unit · integration · evals · fakes
```

## License

MIT — see [`LICENSE`](LICENSE).
