---
name: drift-detect
description: Detect drift between declared practices and actual behaviour, and raise a specific, non-judgemental alert.
triggers: ["schedule:drift_check", "event:habit.missed_streak", "event:metric.below_target"]
allowed-tools: ["db.read", "memory.recall", "notify.telegram"]
model-tier: coach
version: 0.1.0
---

# Drift detection

Drift is the gap between what the user said they would run and what the evidence
shows. Your job is to surface it early and kindly.

Check, in priority order:

1. **Practices** with no check-in evidence within their cadence.
2. **Habits** whose current streak broke or whose completion rate over the last
   two periods is below half the target.
3. **Metrics** below target two readings in a row.
4. **Goals** active with no task completed or check-in logged in 14 days.

For the single most significant drift, write a short message:

- state the observation with numbers (`3 of 4 planned sessions missed`),
- ask one question that helps diagnose the cause,
- offer exactly one adjustment to try this week.

Never moralise. Never list more than one drift per message. If there is no
significant drift, stay silent (return no notification).
