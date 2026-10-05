"""Pure function tests for app.career.fraud — no DB, no mocking, each signal isolated."""

import pytest

from app.career import fraud
from app.career.fraud import HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD, assess_fraud_risk

_BASE_KWARGS = {
    "description_text": "A perfectly ordinary job description with no red flags at all.",
    "salary_min": 80_000,
    "salary_max": 100_000,
    "company_domain": "acme.example.com",
    "source_url": "https://acme.example.com/careers/1",
    "source_channel": "manual_url",
    "employer_verification_status": "verified",
}


def test_clean_posting_is_low_risk_with_no_signals() -> None:
    result = assess_fraud_risk(**_BASE_KWARGS)
    assert result.risk_level == "low"
    assert result.risk_score == 0
    assert result.signals == []


def test_upfront_payment_request_is_flagged() -> None:
    kwargs = dict(_BASE_KWARGS, description_text="You must pay a processing fee before starting.")
    result = assess_fraud_risk(**kwargs)
    codes = [s.code for s in result.signals]
    assert "upfront_payment_request" in codes


def test_sensitive_info_requested_is_flagged() -> None:
    kwargs = dict(
        _BASE_KWARGS,
        description_text="Please send your social security number to begin onboarding.",
    )
    result = assess_fraud_risk(**kwargs)
    assert "sensitive_info_requested_upfront" in [s.code for s in result.signals]


def test_employer_suspicious_status_is_flagged() -> None:
    kwargs = dict(_BASE_KWARGS, employer_verification_status="suspicious")
    result = assess_fraud_risk(**kwargs)
    assert "employer_suspicious" in [s.code for s in result.signals]


def test_employer_unconfirmed_status_is_flagged() -> None:
    kwargs = dict(_BASE_KWARGS, employer_verification_status="unconfirmed")
    result = assess_fraud_risk(**kwargs)
    assert "employer_unconfirmed" in [s.code for s in result.signals]


def test_employer_verified_status_is_not_flagged() -> None:
    result = assess_fraud_risk(**_BASE_KWARGS)
    assert "employer_unconfirmed" not in [s.code for s in result.signals]
    assert "employer_suspicious" not in [s.code for s in result.signals]


def test_company_domain_mismatch_is_flagged_for_manual_url() -> None:
    kwargs = dict(_BASE_KWARGS, source_url="https://totally-unrelated-site.example/job/1")
    result = assess_fraud_risk(**kwargs)
    assert "company_domain_mismatch" in [s.code for s in result.signals]


def test_company_domain_mismatch_not_flagged_for_known_ats_domain() -> None:
    """A Greenhouse/Lever/Ashby-hosted apply page legitimately differs from the employer's
    own domain — that's normal, not a red flag."""
    kwargs = dict(_BASE_KWARGS, source_url="https://boards.greenhouse.io/acme/jobs/1")
    result = assess_fraud_risk(**kwargs)
    assert "company_domain_mismatch" not in [s.code for s in result.signals]


def test_company_domain_mismatch_not_checked_for_board_channels() -> None:
    """Board-polled postings don't have a comparable source_url/company_domain pairing —
    the check is scoped to manual_url captures only."""
    kwargs = dict(
        _BASE_KWARGS,
        source_channel="greenhouse",
        source_url="https://totally-unrelated-site.example/job/1",
    )
    result = assess_fraud_risk(**kwargs)
    assert "company_domain_mismatch" not in [s.code for s in result.signals]


def test_personal_email_for_corporate_contact_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fraud, "_FREE_EMAIL_DOMAINS", frozenset({"example.com"}))
    kwargs = dict(
        _BASE_KWARGS,
        description_text="Contact our recruiter directly at person-09@example.com to apply.",
    )
    result = assess_fraud_risk(**kwargs)
    assert "personal_email_for_corporate_contact" in [s.code for s in result.signals]


def test_corporate_email_is_not_flagged() -> None:
    kwargs = dict(
        _BASE_KWARGS, description_text="Contact our recruiter at careers@acme.example.com."
    )
    result = assess_fraud_risk(**kwargs)
    assert "personal_email_for_corporate_contact" not in [s.code for s in result.signals]


def test_urgency_pressure_language_is_flagged() -> None:
    kwargs = dict(
        _BASE_KWARGS, description_text="Start immediately, no interview necessary. Act now!"
    )
    result = assess_fraud_risk(**kwargs)
    assert "urgency_pressure_language" in [s.code for s in result.signals]


def test_inverted_salary_range_is_flagged() -> None:
    kwargs = dict(_BASE_KWARGS, salary_min=150_000, salary_max=100_000)
    result = assess_fraud_risk(**kwargs)
    assert "salary_range_implausible" in [s.code for s in result.signals]


def test_implausibly_wide_salary_range_is_flagged() -> None:
    kwargs = dict(_BASE_KWARGS, salary_min=20_000, salary_max=200_000)
    result = assess_fraud_risk(**kwargs)
    assert "salary_range_implausible" in [s.code for s in result.signals]


def test_normal_salary_range_is_not_flagged() -> None:
    result = assess_fraud_risk(**_BASE_KWARGS)
    assert "salary_range_implausible" not in [s.code for s in result.signals]


def test_missing_salary_does_not_crash_or_flag() -> None:
    kwargs = dict(_BASE_KWARGS, salary_min=None, salary_max=None)
    result = assess_fraud_risk(**kwargs)
    assert "salary_range_implausible" not in [s.code for s in result.signals]


def test_risk_level_thresholds() -> None:
    # Single high-weight signal (40) stays below the high threshold (50) but crosses medium.
    kwargs = dict(_BASE_KWARGS, description_text="Please pay a processing fee to begin.")
    result = assess_fraud_risk(**kwargs)
    assert MEDIUM_RISK_THRESHOLD <= result.risk_score < HIGH_RISK_THRESHOLD
    assert result.risk_level == "medium"

    # Two signals (40 + 40 = 80) crosses the high threshold.
    kwargs = dict(
        _BASE_KWARGS,
        description_text=(
            "Please pay a processing fee to begin, and send your social security number."
        ),
    )
    result = assess_fraud_risk(**kwargs)
    assert result.risk_score >= HIGH_RISK_THRESHOLD
    assert result.risk_level == "high"


def test_every_fired_signal_is_reported_not_just_the_final_label() -> None:
    """A 'high' verdict must always be traceable to specific reasons, not an opaque score."""
    kwargs = dict(
        _BASE_KWARGS,
        description_text=(
            "Wire transfer required. Send your bank account number. Act now, no interview!"
        ),
    )
    result = assess_fraud_risk(**kwargs)
    codes = {s.code for s in result.signals}
    assert "upfront_payment_request" in codes
    assert "sensitive_info_requested_upfront" in codes
    assert "urgency_pressure_language" in codes
    assert all(s.description for s in result.signals)
