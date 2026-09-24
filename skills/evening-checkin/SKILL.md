---
name: evening-checkin
description: Run the evening check-in - collect habit outcomes, metric values, energy and mood, and a short reflection.
triggers: ["schedule:evening_checkin", "user:log", "topic:today"]
allowed-tools: ["db.read", "db.write", "notify.telegram"]
model-tier: triage
version: 0.1.0
---

# Evening check-in

Close the loop on the day.

1. For each habit due today without a `habit.logged` check-in, ask a single
   yes/no question (rendered as a poll by the Telegram layer).
2. For each metric on cadence, ask for today's value.
3. Ask for energy (1-5) and mood (1-5) as a single poll.
4. Ask one reflection question chosen from: *What went well?*, *What got in the
   way?*, *What will you do differently tomorrow?*

Record every answer as a `checkin` command. Never fabricate values; if the user
skips, record nothing and move on. Keep it to at most five questions total.
