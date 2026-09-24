---
name: weekly-review
description: Run the weekly review - summarize practices, surface drift, and propose concrete adjustments to practices, tasks and cadence.
triggers: ["schedule:weekly_review", "user:review", "event:review.due", "topic:reviews"]
allowed-tools: ["db.read", "db.write", "memory.recall", "notify.telegram"]
model-tier: coach
version: 0.1.0
---

# Weekly review

Compare **evidence** (habits, metrics, check-ins) against **policy** (practices) and
propose adjustments.

Produce a structured review:

- **Scorecard** — per practice: planned vs actual, streak, trend.
- **Metrics** — table of metric, target, average, direction.
- **Wins** — 2-3 concrete wins drawn from check-ins and completed tasks.
- **Drift** — practices that ran below cadence, goals with no progress, metrics
  below target. State the likely cause, not just the symptom.
- **Adjustments** — at most three changes. Each must name the entity it changes
  (`practice_id`, `habit_id`, `task_id`), the change, and the expected effect.
- **Next week** — one sentence naming the single most important outcome.

Persist the narrative to `Review.summary` and the structured changes to
`Review.adjustments`. Propose — do not silently rewrite a practice.
