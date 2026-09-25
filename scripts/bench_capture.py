#!/usr/bin/env python
"""Capture-latency benchmark (dev tool).

Enqueues `agent.run` captures one at a time against a running stack and reports
wall-clock latency from enqueue to the notification being marked sent, plus the
agent run duration from `run_logs`. Use it for A/B comparisons of model/agent
changes.

Usage:
    uv run python scripts/bench_capture.py --count 3
    uv run python scripts/bench_capture.py --count 3 --label "light model + lazy memory"
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, "src")

from sqlalchemy import select

from apollo.bootstrap import bootstrap
from apollo.db import tables as t
from apollo.queue.jobs import enqueue_job

TEXTS = [
    "remind me to water the plants",
    "remind me to pay the water bill",
    "remind me to reply to Alex",
    "remind me to buy coffee beans",
    "remind me to stretch for five minutes",
]


def measure_one(rt, chat: int, rid: str, text: str, timeout: float = 120.0) -> dict:
    t0 = datetime.now(UTC)
    with rt.db.write() as session:
        enqueue_job(
            session,
            kind="agent.run",
            priority=1,
            payload={
                "run_id": rid,
                "text": text,
                "topic": "inbox",
                "telegram_user_id": chat,
                "stream": {
                    "chat_id": chat,
                    "draft_id": random.randint(1, 2**31 - 1),
                    "can_stop": True,
                },
            },
        )
    sent_at = None
    deadline = time.time() + timeout
    while time.time() < deadline and sent_at is None:
        with rt.db.session() as session:
            row = session.execute(
                select(t.Notification).where(t.Notification.ref_id == rid).order_by(t.Notification.id.desc())
            ).scalars().first()
        if row is not None and row.status == "sent":
            sent_at = row.sent_at
        time.sleep(0.1)
    with rt.db.session() as session:
        run = session.execute(
            select(t.RunLog).where(t.RunLog.run_id == rid).order_by(t.RunLog.id.desc())
        ).scalars().first()
    total = (sent_at - t0).total_seconds() if sent_at else None
    return {
        "text": text,
        "total": total,
        "run_ms": run.duration_ms if run else None,
        "status": run.status if run else "no-runlog",
        "model": run.model if run else "?",
        "tools": len(run.tool_calls or []) if run else 0,
        "error": (run.error or "")[:70] if run else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--label", default="")
    parser.add_argument("--warmup", action="store_true", default=True)
    args = parser.parse_args()

    rt = bootstrap()
    chat = rt.settings.telegram.allowed_user_ids[0]
    model = rt.settings.model_for("triage")

    if args.label:
        print(f"# {args.label}")
    print(f"model(triage)={model}\n")

    if args.warmup:
        measure_one(rt, chat, f"bench-{int(time.time())}-warmup", "remind me to warm up")
        time.sleep(0.4)

    results = []
    for i in range(1, args.count + 1):
        text = TEXTS[(i - 1) % len(TEXTS)]
        r = measure_one(rt, chat, f"bench-{int(time.time())}-{i}", text)
        results.append(r)
        total = f"{r['total']:.1f}s" if r["total"] is not None else "TIMEOUT"
        run_ms = f"{r['run_ms']}ms" if r["run_ms"] is not None else "-"
        print(
            f"{text:34s} total={total:>8s} run={run_ms:>7s} status={r['status']:6s} "
            f"tools={r['tools']} {r['error']}"
        )

    totals = [r["total"] for r in results if r["total"] is not None]
    runs = [r["run_ms"] for r in results if r["run_ms"] is not None]
    if totals:
        print(
            f"\nTOTAL end-to-end: avg={sum(totals)/len(totals):.1f}s "
            f"min={min(totals):.1f}s max={max(totals):.1f}s (n={len(totals)})"
        )
    if runs:
        print(f"agent run:       avg={sum(runs)/len(runs):.0f}ms min={min(runs)}ms max={max(runs)}ms")
    errors = [r for r in results if r["status"] != "ok"]
    if errors:
        print(f"non-ok runs: {len(errors)}/{len(results)}")
    rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
