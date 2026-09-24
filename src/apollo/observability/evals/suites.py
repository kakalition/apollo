"""Evaluation suites (``pydantic-evals``), run against a live or replay model.

These definitions are import-safe and offline; the tasks that call a model live in
``apollo.observability.evals.tasks``. Run with ``pytest -m eval`` once a provider is
configured.
"""

from __future__ import annotations

from typing import Any

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Contains, EqualsExpected, IsInstance

TRIAGE_CASES = [
    Case(
        name="single_task",
        inputs="remind me to call the bank tomorrow",
        expected_output="capture_task",
    ),
    Case(
        name="multiple_tasks",
        inputs="buy milk, book dentist, and email the landlord",
        expected_output="capture_tasks",
    ),
    Case(
        name="reflection",
        inputs="today felt heavy, I kept putting off the report",
        expected_output="log_checkin",
    ),
    Case(
        name="goal_intent",
        inputs="I want to get fit enough to run a half marathon",
        expected_output="create_goal",
    ),
]

SKILL_SELECTION_CASES = [
    Case(name="weekly", inputs="it's review day, summarise my week", expected_output="weekly-review"),
    Case(name="decompose", inputs="break my goal into a practice and tasks", expected_output="goal-decompose"),
    Case(name="research", inputs="research whether creatine is worth it", expected_output="deep-research"),
    Case(name="drift", inputs="am I drifting off my practices?", expected_output="drift-detect"),
]

APPROVAL_CASES = [
    Case(name="irreversible_delete", inputs="delete my journal entry about the move", expected_output="pending_approval"),
    Case(name="safe_capture", inputs="add a task to buy stamps", expected_output="applied"),
]

REVIEW_CASES = [
    Case(
        name="review_has_numbers",
        inputs="practices: ran 2 of 4 planned sessions; metric sleep avg 6.4 vs target 7.5",
        expected_output="number",
    )
]


def triage_dataset() -> Dataset[str, str, Any]:
    return Dataset(
        name="triage_intent",
        cases=TRIAGE_CASES,
        evaluators=[EqualsExpected()],
    )


def skill_selection_dataset() -> Dataset[str, str, Any]:
    return Dataset(
        name="skill_selection",
        cases=SKILL_SELECTION_CASES,
        evaluators=[EqualsExpected()],
    )


def approval_routing_dataset() -> Dataset[str, str, Any]:
    return Dataset(
        name="approval_routing",
        cases=APPROVAL_CASES,
        evaluators=[EqualsExpected()],
    )


def review_synthesis_dataset() -> Dataset[str, str, Any]:
    return Dataset(
        name="review_synthesis",
        cases=REVIEW_CASES,
        evaluators=[Contains("number"), IsInstance("str")],
    )


def all_datasets() -> list[Dataset[str, str, Any]]:
    return [
        triage_dataset(),
        skill_selection_dataset(),
        approval_routing_dataset(),
        review_synthesis_dataset(),
    ]
