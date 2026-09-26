"""Gmail and GitHub have no LLM-generated output to evaluate yet — confirmed by grepping both
modules for any LLM usage at all (none exists; Gmail is read-only sync only per CLAUDE.md's own
phase sequencing, GitHub's skill-evidence derivation and readiness review are both deterministic
pattern-matching, already fully covered by exact-assertion unit tests in test_github_sync.py).
These stubs report that honestly rather than fabricating a metric, and give run_all.py the
right shape to activate real buckets here once those features exist."""

from evals.report import BucketReport


def gmail_stub() -> BucketReport:
    return BucketReport(
        name="gmail_read_pipeline",
        applicable=False,
        note=(
            "Not applicable — Gmail is read-only sync only today, no classification or "
            "summarization LLM step exists yet (CLAUDE.md sequences that after read-only). "
            "Nothing in app/gmail/ calls an LLM. This bucket activates once that's built."
        ),
    )


def github_stub() -> BucketReport:
    return BucketReport(
        name="github_assistant",
        applicable=False,
        note=(
            "Not applicable — GitHub has no LLM-generated summary. Skill-evidence derivation "
            "(app/github/derive.py) and the recruiter-readiness review are both deterministic "
            "pattern-matching with no model call, already covered by exact-assertion unit "
            "tests (test_github_sync.py) rather than a quality eval. Capacity redirected to "
            "the Career Intelligence bucket instead, per the approved plan."
        ),
    )
