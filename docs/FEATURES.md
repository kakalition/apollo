# Apollo — Features & Use Cases

Apollo is a **single-user, local-first personal operating system**. You declare goals,
Apollo turns them into practices / projects / tasks / habits / metrics, a scheduler
drives check-ins and reviews, and agents use skills + MCP tools to do work and keep
you accountable.

Everything lives on your machine (SQLite + markdown vault + local Chroma). The only
outbound traffic is your model/embeddings endpoint, Telegram, and MCP servers you
configure.

Status legend used throughout:

| Mark | Meaning |
|---|---|
| ✅ | Implemented and wired |
| ◻️ | Available in the code, not auto-wired (enable/configure or call it) |
| ⛔ | Out of scope for v1 |

---

## Table of contents

1. [Mental model](#1-mental-model)
2. [Feature map by subsystem](#2-feature-map-by-subsystem)
3. [How one message becomes work](#3-how-one-message-becomes-work)
4. [Exhaustive use cases](#4-exhaustive-use-cases)
5. [Built-in routines & predicates](#5-built-in-routines--predicates)
6. [Command & API reference](#6-command--api-reference)
7. [Current install state & limits](#7-current-install-state--limits)

---

## 1. Mental model

> A **Goal** is what you want. A **Practice** is what you run to get it.
> Everything else hangs off those two.

| You describe… | Apollo models it as | Acts on it via |
|---|---|---|
| wanted outcome | `Goal` | Planner + horizon/progress checks |
| ongoing behaviour with cadence | `Practice` | Planner/Coach + `review_cadence` audit |
| finite deliverable | `Project` (`done_when`) | Planner + due proximity |
| something that repeats (rrule) | `Habit` (`rrule`, streaks) | Coach + `habit_streak_broken` |
| one action | `Task` (may be unparented → inbox) | Triage/Planner + `overdue_tasks(n)` |
| something measured | `Metric` (unit, target, direction) | Coach + `metric_below_target` |
| logged evidence | `CheckIn` | feeds reviews + memory |
| reflection over a period | `Review` | Coach synthesis |
| free-form note | `JournalEntry` (+ FTS) | lexical search + memory |

Evidence → reviews → rewritten practices is the closed loop.

---

## 2. Feature map by subsystem

### 2.1 Domain & storage ✅

- 12 domain entities + 10 infrastructure tables (`events`, `jobs`, `pending_actions`,
  `notifications`, `audit_log`, `schedule_rules`, `run_logs`, `settings`,
  `conversations`, FTS index).
- SQLAlchemy 2.0 + Alembic migration; timezone-aware datetimes stored as UTC ISO text.
- **Transaction outbox**: every mutation writes its `events` row in the same
  transaction as the change.
- **FTS5** (`porter unicode61`) over `data/vault/*.md`; hashing sync reindexes only on
  change and removes deleted files.
- Path-sandboxed vault (no escaping the vault root).

### 2.2 Process model & concurrency ✅

Five processes over one SQLite DB (WAL): `apollo telegram`, `apollo worker`,
`apollo dispatcher`, `apollo mcp`, and the `apollo` CLI.

- `BEGIN IMMEDIATE` + `busy_timeout=5000` on every write; a worker never holds the
  write lock across a model call.
- Job claim is one atomic `UPDATE … RETURNING`; leases + heartbeat; expired leases
  requeued; exponential backoff → `dead`.
- Single-dispatcher invariant enforced by a DB advisory lock.
- Kill switch: `apollo pause` halts job claiming + scheduled runs (Telegram keeps
  receiving).

### 2.3 Agent runtime ✅

- **Supervisor → specialists**: `triage`, `planner`, `coach`, `researcher`.
- Tier routing (`triage` / `plan` / `coach` / `research` / `memory`).
- Typed outputs: `CommandBatch`, `RouteDecision`, `CoachResult`, `ResearchResult`.
- Per-run `RunLog` (agent, tier, model, tool calls, tokens, duration, status).
- Least-privilege tool capabilities: `db.read`, `db.write`, `memory.recall`,
  `memory.remember`, `notify.telegram`, `skills.load`, `approval.request`.
- **Streaming** to Telegram drafts + **Stop** (cross-process cancellation via DB flag) ✅.
- OpenAI-compatible transport adapter that repairs non-standard provider `metadata`.

### 2.4 Skills ✅

Markdown-first with progressive disclosure: the supervisor sees only `name: description`;
the body loads on demand via `load_skill`. Optional `tools.py` gated by `allowed-tools`.
Hot reload via watchdog.

Built-ins: `capture`, `daily-briefing`, `evening-checkin`, `weekly-review`,
`goal-decompose`, `drift-detect`, `deep-research`.

### 2.5 Tools ✅

`db_tools` (all reads/writes), `Notifier` (writes to the outbox, never sends inline),
clock/time windows, vault.

### 2.6 MCP — both directions ✅

- **Client (consume)**: config-declared servers, default-deny allowlist, namespacing
  (`vault.read`), stdio/SSE/streamable-HTTP, cwd pinned to the project root. The
  bundled `vault` server is verified live.
- **Server (expose Apollo)**: `apollo mcp` stdio with free reads, approval-aware writes,
  and skills exposed as MCP prompts.

### 2.7 Memory ✅ (live-verified)

`Memory` facade → **Mem0 over a local Chroma server**, embeddings via your
`/embeddings` endpoint, cheap-tier LLM for extraction. Writes happen only in the
worker. `reindex` rebuilds from vault + DB. Fallback chain if a provider serves no
embeddings: second provider → local `fastembed`.

### 2.8 Scheduler ✅

Time (cron), event subscriptions, and **safe registered predicates** (no `eval`).
Cooldowns, catch-up after downtime, timezone-aware, quiet hours.

### 2.9 Telegram (native Bot API 10.3) — mixed

- ✅ Long polling with exact `allowed_updates`; user-id allowlist; `/commands`; menu
  button; profile name/description.
- ✅ **Streaming drafts** + Stop; ✅ `sendMessage` HTML with escaping + 4096 chunking;
  ✅ inline keyboards with disabled states; ✅ approvals; ✅ `setMessageReaction` ack on
  capture; ✅ polls **inbound** (`poll_answer` → CheckIn/Metric); ✅ deep links
  (`start=capture_<b64url>`); ✅ inline mode.
- ✅ **Topics optional**: single-chat natural language is the default; nine-topic
  routing is available when `topic_routing = true`.
- ✅ Notifications outbox: per-chat throttle, 429 `retry_after`, idempotency
  `(kind, ref_id, period)`, quiet-hours buffering.
- ◻️ Rich-block documents are rendered (`RichDocument`) but the drainer sends rich HTML
  for reliability.
- ◻️ Poll **sending** helpers exist; no routine/agent tool triggers them yet.
- ◻️ `pinChatMessage` dashboards, `message_effect_id` milestones, TTS `sendVoice`.
- ⛔ Native checklists (Business-scoped) → callback-checkbox fallback is used; Mini App,
  ephemeral messages, guest mode, Stars/payments, business/secretary mode.

### 2.10 Safety & autonomy ✅

| Tier | Policy |
|---|---|
| `read` | free |
| `mutate` | auto-applied **+ `audit_log` + notify** |
| `irreversible` | creates `pending_actions`, needs Telegram approval, auto-denies on expiry |

Secrets live in a git-ignored `.env` (0600) and are redacted in logs. MCP/web output is
untrusted data (stated to every agent). No arbitrary shell execution.

### 2.11 Observability & evals — mixed

- ✅ JSONL + console logs, `RunLog`, `audit_log`.
- ✅ `pydantic-evals` datasets (triage intent, skill selection, approval routing, review
  synthesis) plus offline wiring tests.
- ◻️ Live eval tasks are defined; run with `pytest -m eval`.
- ✅ OTel/Logfire tracing, opt-in (off by default).

---

## 3. How one message becomes work

```
Telegram text ──► handle_message ──► enqueue job(agent.run)
                                        │
                       (no agent set) supervisor routes → triage/planner/coach/researcher
                                        │
   worker claims job ──► agent runs (tools: db.read/write, memory, notify, skills)
                                        │
        output is typed commands ──► applied in ONE write txn ──► events (task.created…)
                                        │
   dispatcher drains events ──► reactions (memory.add, notify.send, approval.resume)
                                        │            + event schedule rules
   notifications outbox ──► Telegram drainer ──► sendMessage (throttled, quiet hours)
```

Cron routines enqueue the same job kinds (`briefing.generate`, `review.generate`,
`skill.run`, `vault.sync`, `overdue.sweep`).

---

## 4. Exhaustive use cases

Each case is written as **you say → Apollo does → guardrail**.

### A. Capture & triage

| # | You say | Apollo does |
|---|---|---|
| 1 | “remind me to call the bank tomorrow” | `capture_task(due=tomorrow)` → `task.created`; ✅ ack reaction on your message |
| 2 | “buy milk, book dentist, email landlord” | three `capture_task`s in one batch |
| 3 | “add ‘research standing desk’ to the inbox” | unparented task (inbox); parents are never forced |
| 4 | “note that the landlord is coming Thursday at 9” | `capture_note` → markdown in vault → FTS + `journal.captured` → `memory.add` |
| 5 | “today felt heavy, I kept avoiding the report” | `log_checkin(reflection)` with friction → feeds drift detection |
| 6 | voice note | local STT (if `voice` extra installed) → same triage path ◻️ |
| 7 | deep link `?start=capture_<b64url>` | captures shared text from iOS Shortcuts / share sheets |
| 8 | `/capture <text>` · `/log <text>` | explicit capture |
| 9 | ambiguous text | triage returns exactly one clarifying question instead of guessing |

### B. Goals & planning

| # | You say | Apollo does |
|---|---|---|
| 10 | “I want to run a half marathon in 6 months” | supervisor → planner → `create_goal` + `create_practice` + first tasks + metric/habit as justified |
| 11 | “break my goal into a practice and first tasks” | `goal-decompose` skill |
| 12 | “mark the ‘Get fit’ goal achieved” | `update_goal(status=achieved)` → `goal.achieved` → milestone notification |
| 13 | “that goal is stalled, re-plan it” | planner re-reads tasks/practices and proposes adjustments (audited) |
| 14 | “make this a project with a done_when” | `create_project` + attaches tasks |
| 15 | a goal with nothing recurring | Practice + Project + Tasks (classification test enforced by unit tests) |
| 16 | unparented captures | Planner files them (`what_should_i_do_now`, `list_tasks`) |

### C. Practices, habits, metrics

| # | You say | Apollo does |
|---|---|---|
| 17 | “log a 6 for sleep” | `log_metric` → `metric.recorded`; below target → `metric.below_target` → notify |
| 18 | “I ran today” | `log_habit` → streak up → `habit.logged` |
| 19 | a missed daily habit | predicate `habit_streak_broken(id)` → `habit.missed_streak` → drift skill |
| 20 | “meditate daily” | Practice + Habit kept 1:1 (durable parent for metrics/reviews) |
| 21 | a metric with no goal | allowed (`goal_id` nullable) |

### D. Daily operation

| # | Trigger | Apollo does |
|---|---|---|
| 22 | 07:00 cron | `briefing.generate` → focus / habits / metrics / watch-out / one remembered context |
| 23 | `/today` | briefing on demand (streamed draft, then final) |
| 24 | `/focus` | ranked “what should I do now” with reasons (overdue > due today > high priority > habit due) |
| 25 | reply-keyboard tap | `✅ Done · ⏭ Skip · 🕐 Later · 📝 Note · 🎤 Voice` ◻️ currently maps to text, not full habit logging |
| 26 | 21:00 cron | `evening-checkin` skill asks ≤5 questions; poll mapping exists for `poll_answer` ◻️ (sending not auto-wired) |
| 27 | quiet hours 22:00–07:00 | non-urgent notifications buffered until 07:00 |

### E. Reviews & drift

| # | Trigger | Apollo does |
|---|---|---|
| 28 | Sun 18:00 cron | `review.generate` → `weekly-review`: scorecard, metrics table, wins, drift with likely cause, ≤3 adjustments, next week |
| 29 | `review.due` event | review surfaces |
| 30 | daily 08:00 | `drift-detect` skill → one specific, non-judgemental alert (or silent) |
| 31 | condition `no_checkin_days(2)` | seeded but disabled nudge |
| 32 | `/review` | latest review summary |
| 33 | `complete_review` | writes `Review.summary/insights/adjustments` → `review.completed` → memory |

### F. Memory

| # | Trigger | Apollo does |
|---|---|---|
| 34 | journal / check-ins / reviews | auto-ingest via `memory.add` jobs (worker-only) |
| 35 | planner/coach runs | `recall_memory` + top-k context injection |
| 36 | “remember that Sam’s birthday is 12 May” | extracted, deduped memory (verified live; 1536-dim recall returned the right memory) |
| 37 | `apollo memory reindex` | rebuilds memories from vault + DB |
| 38 | provider without embeddings | config-selectable fallback (second provider → local `fastembed`) |

### G. Research / executor

| # | You say | Apollo does |
|---|---|---|
| 39 | “research whether creatine is worth it” | `deep-research`: 2–4 searches, cited findings vs interpretation, recommendation + counter-argument; offers to save to vault |
| 40 | “what’s on my calendar next week?” | MCP web/calendar tools under allowlist; tool output treated as data, never instructions ◻️ needs a calendar server |
| 41 | “block 30m to write the report” | calendar write (approval-gated if irreversible) ◻️ needs a calendar server |

### H. External agents via MCP server ✅

| # | Surface | Tools |
|---|---|---|
| 42 | Claude Desktop / Kilo / Cursor reads | `get_context`, `today`, `what_should_i_do_now`, `list_goals`, `get_goal`, `list_practices`, `list_tasks`, `list_habits`, `get_review`, `search_vault`, `recall_memory` |
| 43 | writes | `create_goal`, `update_goal`, `create_practice`, `create_project`, `create_task`, `complete_task`, `log_checkin`, `log_metric`, `complete_review`, `capture_note` → `applied` or `pending_approval` |
| 44 | prompts | each skill as `skill-<name>` ◻️ not yet opened from a real client here |

### I. Approvals & autonomy ✅

| # | Trigger | Apollo does |
|---|---|---|
| 46 | agent calls `request_approval` / MCP hits an irreversible tool | `approval.requested` → Telegram message with ✅ / ✏️ / ❌ |
| 47 | tap Approve | `approval.granted` → `approval.resume` continues the work; Deny stops it; expiry auto-denies |
| 48 | `/approve` | lists pending approvals; every decision written to `audit_log` |
| 49 | config | `[autonomy].irreversible` in `apollo.toml` defines what needs approval |

### J. Scheduling & customisation

| # | Action | How |
|---|---|---|
| 50 | inspect / toggle routines | `apollo schedule list` / `schedule toggle <name>` |
| 51 | add an event rule | e.g. on `goal.created` run `goal-decompose` with a cooldown |
| 52 | add a condition rule | e.g. `metric_below_target(<id>)` → `drift-detect` skill |
| 53 | hourly overdue sweep | `overdue.sweep` → `task.overdue` → notification |

### K. Skills authoring

| # | Action | How |
|---|---|---|
| 54 | new pure-prompt skill | one `skills/<slug>/SKILL.md` (frontmatter: `name`, `description`, `triggers`, `allowed-tools`, `model-tier`); hot-reloaded |
| 55 | Python-backed skill | add `skills/<slug>/tools.py` exporting `register(registry)`; tools filtered by `allowed-tools` |
| 56 | discover skills | `/skills`, or list `skills/` on disk (progressive disclosure keeps prompts small) |

### L. Voice — partial

| # | Direction | Status |
|---|---|---|
| 57 | **in** (capture) | voice → download → local `faster-whisper` → triage ✅ code, ◻️ extra not installed |
| 58 | **out** (briefing) | TTS to OGG/Opus via `sendVoice` ✅ helper, ◻️ not wired to a setting/routine |

### M. Ops & admin ✅

| # | Command | What it does |
|---|---|---|
| 59 | `apollo doctor` | DB, vault, provider, embeddings (+dims), Chroma, Telegram topics |
| 60 | `apollo init-db` · `upgrade` · `schema` | schema + seed areas/routines; migrations |
| 61 | `apollo pause` / `resume` / `status` | kill switch; queue depth, pause flag, pending approvals |
| 62 | `apollo queue list\|retry\|replay\|purge` | inspect/repair jobs and dead letters |
| 63 | `apollo worker` / `dispatcher` (`--once`) | run one pass; `scripts/run.sh start\|stop\|status` |
| 64 | `apollo topics list\|reset`, `apollo mcp-servers list\|check` | topics state; MCP registry health |
| 65 | `scripts/com.apollo.plist`, `scripts/apollo.service` | launchd / systemd templates |

### N. Privacy & security posture ✅

| # | Guarantee |
|---|---|
| 66 | Everything local (SQLite, vault, Chroma on loopback); a single-user allowlist rejects other Telegram users |
| 67 | Secrets never logged; `.env` is 0600 and git-ignored; config dumps are redacted |
| 68 | No arbitrary shell; the vault is path-sandboxed; every agent is told the prompt-injection boundary |

---

## 5. Built-in routines & predicates

| Routine | When | Does |
|---|---|---|
| `morning_briefing` | 07:00 daily | `briefing.generate` |
| `evening_checkin` | 21:00 daily | `skill.run evening-checkin` |
| `weekly_review` | Sun 18:00 | `review.generate` |
| `drift_check` | 08:00 daily | `skill.run drift-detect` |
| `overdue_sweep` | hourly | mark overdue → notify |
| `vault_sync` | every 5 min | reconcile vault → journal + FTS |
| `no_checkin_nudge` | condition, **disabled** | `no_checkin_days(2)` → drift skill |

Condition predicates: `no_checkin_days(n)`, `metric_below_target(id)`,
`habit_streak_broken(id)`, `goal_no_progress_days(n)`, `overdue_tasks(n)`.

Event types on the bus: `goal.created/updated/achieved`, `practice.created/updated`,
`project.created/updated`, `task.created/updated/completed/overdue`,
`habit.created/logged/missed_streak`, `metric.created/recorded/below_target`,
`checkin.logged`, `review.due/completed`, `journal.captured`, `message.received`,
`job.failed`, `approval.requested/granted/denied`.

Job kinds: `agent.run`, `skill.run`, `memory.add`, `memory.reindex`, `vault.sync`,
`notify.send`, `schedule.evaluate`, `approval.resume`, `review.generate`,
`briefing.generate`, `overdue.sweep`.

---

## 6. Command & API reference

### Telegram commands

`/start` · `/help` · `/settings` · `/today` · `/capture <text>` · `/log <text>` ·
`/goals` · `/practices` · `/habits` · `/review` · `/focus` · `/memory` · `/skills` ·
`/approve` · `/pause` · `/resume`

### CLI

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

### MCP server tools (stdio)

Read: `get_context`, `today`, `what_should_i_do_now`, `list_goals`, `get_goal`,
`list_practices`, `list_tasks`, `list_habits`, `get_review`, `search_vault`,
`recall_memory`.
Write (approval-aware): `create_goal`, `update_goal`, `create_practice`,
`create_project`, `create_task`, `complete_task`, `log_checkin`, `log_metric`,
`complete_review`, `capture_note`.
Prompts: `skill-<name>` for each loaded skill.

---

## 7. Current install state & limits

- Single chat, natural language routed by the supervisor (`topic_routing = false`).
- Chat model + embeddings on OpenRouter; embeddings live (1536 dims); Chroma running;
  Mem0 verified end-to-end.
- Telegram topics were provisioned earlier but are now ignored; turn the BotFather
  toggle **off** to remove the UI (`apollo topics reset` clears stored state).
- Not installed / not wired: `voice` extra, calendar and web MCP servers, live evals,
  rich-block delivery, pinned dashboards, message effects, TTS briefings, native
  checklists.
- Quality gate: `ruff` clean · `pyright` 0 errors · `pytest` 98 passed.

### Explicitly out of scope (v1)

Web UI, multi-user/auth, native mobile app, durable execution engine
(Temporal/DBOS), large-corpus RAG, cloud hosting, and — for Telegram — the Mini App,
Ephemeral messages, Guest mode, bot-to-bot communication, managed bots,
Business/Secretary mode, Telegram Stars/payments, HTML5 games, and attachment-menu
integration.
