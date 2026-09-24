---
name: goal-decompose
description: Decompose a goal into a practice, projects and first tasks, with success criteria and a review cadence.
triggers: ["user:goal", "event:goal.created", "topic:goals"]
allowed-tools: ["db.read", "db.write"]
model-tier: plan
version: 0.1.0
---

# Goal decomposition

Turn a wanted outcome into something runnable.

1. Restate the goal as an outcome with a measurable success criterion and a
   horizon (`horizon_start`, `horizon_end`).
2. Define the **practice**: the repeatable behaviour that produces the goal.
   Give it a `cadence` (e.g. `3x/week`) and a `review_cadence`.
3. Define **projects** only where there is a finite deliverable with a
   `done_when`. Not every goal needs a project.
4. Define the first **3 tasks** that unblock everything else. Keep each under a
   day of work and attach it to the project or practice.
5. Define **habits** (with `rrule` and `target_per_period`) and **metrics**
   (with unit and target) that will provide evidence at review time.

Apply the classification test: wanted → goal, practised → practice, completable →
project, repeats → habit, single action → task, measures → metric. Do not create an
entity you cannot justify with a trigger that will act on it.
