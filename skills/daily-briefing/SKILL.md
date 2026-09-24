---
name: daily-briefing
description: Produce the morning briefing - today's focus, due and overdue tasks, habit prompts, metric targets and one piece of context worth remembering.
triggers: ["schedule:morning_briefing", "user:today", "topic:today"]
allowed-tools: ["db.read", "memory.recall", "notify.telegram"]
model-tier: coach
version: 0.1.0
---

# Daily briefing

Produce a concise briefing the user can act on in 30 seconds.

Sections, in order:

1. **Focus** — at most three items. Prefer tasks due today, then overdue, then the
   highest-priority open task on an active goal. Explain *why* in one clause.
2. **Practices & habits** — which habits are due today and their current streak.
3. **Metrics** — any metric below target, with its most recent value.
4. **Watch out** — overdue tasks, stalled goals, a broken streak.
5. **Remember** — one relevant memory from `memory.recall`, if useful.

Then propose at most three inline actions as a buttons block: `Done`, `Snooze 1h`,
`Not today`. Keep the whole briefing under 120 words of prose.
