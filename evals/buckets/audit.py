"""Approval/audit adversarial bucket: runs the 25-case set (7 reused from Phase 10's
tests/test_redteam_injection.py unchanged, 18 new in tests/test_redteam_injection_extended.py)
via pytest itself — never reimplemented as a second, parallel assertion system — and reports
tests/test_redteam_isolation.py's pass count alongside it as supporting evidence, without
re-running its cases as if they were new here.

Success metric: 100% of these must pass. A "FINDING"-prefixed test that documents a known,
reported gap still counts as passing (it's asserting today's real, gap-including behavior on
purpose) — a bucket failure here means a case caught something *newly* wrong, not that a
pre-existing, already-flagged gap still exists.
"""

import re
import subprocess
import sys
from pathlib import Path

from evals.config import BACKEND_ROOT
from evals.report import BucketReport, TaskResult

REUSED_FILE = "tests/test_redteam_injection.py"
EXTENDED_FILE = "tests/test_redteam_injection_extended.py"
ISOLATION_FILE = "tests/test_redteam_isolation.py"


def _run_pytest(*paths: str) -> tuple[int, int, str]:
    """Runs pytest as a subprocess (the harness's own venv/interpreter, not a second copy of
    pytest's logic) and returns (passed, failed, raw_output)."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", *paths, "-q", "--no-header"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    passed = failed = 0
    for line in output.splitlines():
        passed_match = re.search(r"(\d+) passed", line)
        if passed_match:
            passed = int(passed_match.group(1))
        failed_match = re.search(r"(\d+) failed", line)
        if failed_match:
            failed = int(failed_match.group(1))
    return passed, failed, output


def run() -> BucketReport:
    tasks: list[TaskResult] = []

    passed, failed, output = _run_pytest(REUSED_FILE, EXTENDED_FILE)
    total = passed + failed
    tasks.append(
        TaskResult(
            task_id="adversarial_cases",
            passed=(failed == 0),
            score=passed / total if total else None,
            detail=(
                f"{passed}/{total} adversarial cases passed "
                f"({REUSED_FILE} reused + {EXTENDED_FILE} new)"
                + ("" if failed == 0 else f" — see: {output[-2000:]}")
            ),
        )
    )

    if (Path(BACKEND_ROOT) / ISOLATION_FILE).exists():
        iso_passed, iso_failed, iso_output = _run_pytest(ISOLATION_FILE)
        iso_total = iso_passed + iso_failed
        tasks.append(
            TaskResult(
                task_id="cross_user_isolation_supporting_evidence",
                passed=(iso_failed == 0),
                score=iso_passed / iso_total if iso_total else None,
                detail=(
                    f"{iso_passed}/{iso_total} isolation cases passed (reported for context, "
                    f"not counted toward the 25 adversarial cases above)"
                    + ("" if iso_failed == 0 else f" — see: {iso_output[-2000:]}")
                ),
            )
        )

    return BucketReport(name="approval_audit_adversarial", tasks=tasks)
