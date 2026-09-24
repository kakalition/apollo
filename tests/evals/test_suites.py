"""Offline smoke check that evaluation suites are wired correctly.

The real evaluation tasks call a live model (see ``apollo.observability.evals``);
this test substitutes a deterministic mapping so the datasets, cases and evaluators
are validated without a provider.
"""

from __future__ import annotations

from apollo.observability.evals import (
    approval_routing_dataset,
    make_offline_task,
    review_synthesis_dataset,
    skill_selection_dataset,
    triage_dataset,
)


async def _run(dataset) -> None:
    mapping = {
        case.inputs: case.expected_output
        for case in dataset.cases
        if isinstance(case.expected_output, str)
    }
    report = await dataset.evaluate(make_offline_task(mapping), progress=False)
    assert len(report.failures) == 0


async def test_triage_dataset_wiring() -> None:
    await _run(triage_dataset())


async def test_skill_selection_dataset_wiring() -> None:
    await _run(skill_selection_dataset())


async def test_approval_routing_dataset_wiring() -> None:
    await _run(approval_routing_dataset())


async def test_review_dataset_wiring() -> None:
    dataset = review_synthesis_dataset()
    report = await dataset.evaluate(
        make_offline_task({c.inputs: "number 6.4" for c in dataset.cases}), progress=False
    )
    assert len(report.failures) == 0
