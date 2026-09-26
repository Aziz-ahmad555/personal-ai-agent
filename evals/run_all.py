#!/usr/bin/env python
"""Eval harness entry point.

    python -m evals.run_all              # --replay (default): free, deterministic, no API calls
    python -m evals.run_all --live       # real calls: real search/LLM/judge, real cost

Buckets: profile/RAG retrieval (hit rate + MRR), the Research Engine (marker-stripping
correctness always; LLM-judge faithfulness scoring + calibration + a real-vs-baseline
comparison in --live only), Career Intelligence (cover-letter/resume verifier precision and
recall against hallucination/injection patterns; one real end-to-end injection check in
--live), Gmail/GitHub (stub — not applicable yet, see evals/buckets/stubs.py), and the
approval/audit system's 25-case adversarial set (reuses Phase 10's red-team tests, extends
with 18 new ones — see evals/buckets/audit.py).
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

if hasattr(sys.stdout, "reconfigure") and (sys.stdout.encoding or "").lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 default

from evals import db as eval_db
from evals.buckets import audit as audit_bucket
from evals.buckets import career as career_bucket
from evals.buckets import research as research_bucket
from evals.buckets import retrieval as retrieval_bucket
from evals.buckets import stubs
from evals.report import BucketReport, EvalReport, TaskResult


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Personal AI Agent eval harness.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Make real search/LLM/judge calls (real cost). Default is --replay.",
    )
    parser.add_argument(
        "--skip-retrieval",
        action="store_true",
        help="Skip the profile/RAG retrieval bucket (it needs a real Postgres+pgvector "
        "database — use this if one isn't available right now).",
    )
    return parser.parse_args()


def _failed_bucket(name: str, error: str) -> BucketReport:
    return BucketReport(
        name=name,
        tasks=[
            TaskResult(
                task_id="setup", passed=False, score=0.0, detail=f"bucket setup failed: {error}"
            )
        ],
    )


async def _run_retrieval_bucket(*, replay: bool) -> BucketReport:
    eval_url = eval_db.eval_database_url()
    session_factory = await eval_db.reset_schema(eval_url)
    return await retrieval_bucket.run(session_factory, replay=replay)


async def _run_live_extras(report: EvalReport) -> None:
    from app.config import get_settings
    from app.research.llm import get_llm_provider

    provider = get_llm_provider(get_settings())

    career_live_task = await career_bucket.run_live_supplementary_check(provider)
    report.buckets.append(BucketReport(name="career_live_injection_check", tasks=[career_live_task]))

    live_research = await research_bucket.run_live_supplementary(provider)
    judge_tasks = list(live_research.scoring_tasks)
    judge_tasks.append(
        TaskResult(
            task_id="judge_calibration_agreement",
            passed=live_research.calibration_agreement_rate >= 0.8,
            score=live_research.calibration_agreement_rate,
            detail=(
                f"judge agreed with human labels on "
                f"{live_research.calibration_agreement_rate:.0%} of the gold set"
                + (
                    f" — disagreements: {'; '.join(live_research.calibration_disagreements)}"
                    if live_research.calibration_disagreements
                    else ""
                )
            ),
        )
    )
    report.buckets.append(BucketReport(name="research_judge_live", tasks=judge_tasks))


async def main() -> None:
    args = _parse_args()
    replay = not args.live
    report = EvalReport(mode="replay" if replay else "live")

    # Gmail / GitHub: always stubs, no mode dependence.
    report.buckets.append(stubs.gmail_stub())
    report.buckets.append(stubs.github_stub())

    # Profile/RAG retrieval: needs a real Postgres+pgvector database.
    if not args.skip_retrieval:
        try:
            report.buckets.append(await _run_retrieval_bucket(replay=replay))
        except Exception as exc:  # noqa: BLE001 - report the failure, don't crash the whole run
            report.buckets.append(_failed_bucket("profile_rag_retrieval", str(exc)))

    # Research Engine: replay-mode marker-stripping checks always run.
    report.buckets.append(await research_bucket.run_replay())

    # Career Intelligence: replay-mode verifier precision/recall always runs.
    report.buckets.append(career_bucket.run_replay())

    # Approval/audit: the 25-case adversarial set (pytest-backed).
    report.buckets.append(audit_bucket.run())

    if not replay:
        await _run_live_extras(report)

    report.finished_at = datetime.now(UTC)
    report.print_console()
    path = report.save_json()
    print(f"\nFull report saved to {path}")

    any_bucket_failed = any(
        b.applicable and b.total_scored > 0 and b.pass_rate is not None and b.pass_rate < 1.0
        for b in report.buckets
    )
    sys.exit(1 if any_bucket_failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
