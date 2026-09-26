"""Deterministic, rule-based fraud/scam signal detection over a job posting's already-
stored fields — never an LLM judgment (CLAUDE.md: "no LLM for deterministic work ...
policy enforcement — plain code"). Each rule is a pure function of the input; the final
risk_level is a templated sum of whichever signals actually fired, so a "high" verdict is
always traceable to specific, inspectable reasons rather than an unexplained model
opinion.

The keyword/regex lists below are a starting curation, not exhaustive — same caveat as
app.research.tiers' domain allowlists. They will under-flag novel scam phrasing and
should be extended over time, never treated as a complete list.
"""

import re
from dataclasses import dataclass

SIGNAL_WEIGHTS: dict[str, int] = {
    "upfront_payment_request": 40,
    "sensitive_info_requested_upfront": 40,
    "employer_suspicious": 50,
    "employer_unconfirmed": 25,
    "company_domain_mismatch": 20,
    "personal_email_for_corporate_contact": 15,
    "urgency_pressure_language": 10,
    "salary_range_implausible": 10,
}

HIGH_RISK_THRESHOLD = 50
MEDIUM_RISK_THRESHOLD = 20

_PAYMENT_PATTERNS = [
    r"processing fee",
    r"registration fee",
    r"training fee",
    r"purchase (?:your own|the) equipment",
    r"wire transfer",
    r"gift card",
    r"western union",
    r"money order",
    r"cryptocurrency payment",
    r"pay(?:ment)? (?:is )?required to (?:start|begin|proceed)",
]

_SENSITIVE_INFO_PATTERNS = [
    r"social security number",
    r"\bssn\b",
    r"bank account number",
    r"routing number",
    r"copy of your (?:passport|id|driver'?s license)",
    r"upload a photo of your (?:id|passport)",
]

_URGENCY_PATTERNS = [
    r"start immediately[,.]? no interview",
    r"no interview (?:necessary|required|needed)",
    r"act now",
    r"apply today only",
    r"limited (?:spots|positions) (?:available )?today",
    r"immediate hire,? no experience needed",
]

_FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
}
_KNOWN_ATS_DOMAINS = {"greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "icims.com"}

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class FraudSignal:
    code: str
    description: str


@dataclass(frozen=True)
class FraudAssessmentResult:
    risk_level: str
    risk_score: int
    signals: list[FraudSignal]


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _registrable_domain(domain: str) -> str:
    parts = domain.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain.lower()


def assess_fraud_risk(
    *,
    description_text: str | None,
    salary_min: int | None,
    salary_max: int | None,
    company_domain: str | None,
    source_url: str | None,
    source_channel: str,
    employer_verification_status: str | None,
) -> FraudAssessmentResult:
    text = description_text or ""
    signals: list[FraudSignal] = []

    if _matches_any(_PAYMENT_PATTERNS, text):
        signals.append(
            FraudSignal(
                "upfront_payment_request",
                "The posting text asks for payment, a fee, or a money transfer before or "
                "as part of starting the role.",
            )
        )

    if _matches_any(_SENSITIVE_INFO_PATTERNS, text):
        signals.append(
            FraudSignal(
                "sensitive_info_requested_upfront",
                "The posting text asks for sensitive personal identifiers (SSN, bank "
                "details, ID copy) before any interview.",
            )
        )

    if employer_verification_status == "suspicious":
        signals.append(
            FraudSignal(
                "employer_suspicious",
                "Employer verification found evidence actively contradicting this "
                "employer's legitimacy.",
            )
        )
    elif employer_verification_status == "unconfirmed":
        signals.append(
            FraudSignal(
                "employer_unconfirmed",
                "Employer verification found no corroborating official source for this employer.",
            )
        )

    if source_channel == "manual_url" and company_domain and source_url:
        source_domain = (
            re.sub(r"^https?://", "", source_url).split("/")[0].lower().removeprefix("www.")
        )
        if (
            _registrable_domain(source_domain) != _registrable_domain(company_domain)
            and _registrable_domain(source_domain) not in _KNOWN_ATS_DOMAINS
        ):
            signals.append(
                FraudSignal(
                    "company_domain_mismatch",
                    f"The posting's page ({source_domain}) doesn't match the claimed "
                    f"employer domain ({company_domain}) and isn't a known job board.",
                )
            )

    email_match = _EMAIL_RE.search(text)
    if email_match and company_domain:
        email_domain = _registrable_domain(email_match.group(1))
        if email_domain in _FREE_EMAIL_DOMAINS:
            signals.append(
                FraudSignal(
                    "personal_email_for_corporate_contact",
                    f"A free personal email domain ({email_domain}) is given as the "
                    "contact, despite a claimed corporate employer.",
                )
            )

    if _matches_any(_URGENCY_PATTERNS, text):
        signals.append(
            FraudSignal(
                "urgency_pressure_language",
                "The posting uses urgency/pressure language (e.g. no interview, act now) "
                "typical of scam postings.",
            )
        )

    if salary_min is not None and salary_max is not None:
        implausible = salary_min > salary_max or (salary_min > 0 and salary_max > salary_min * 5)
        if implausible:
            signals.append(
                FraudSignal(
                    "salary_range_implausible",
                    f"The stated salary range (${salary_min:,}-${salary_max:,}) is "
                    "inverted or implausibly wide.",
                )
            )

    risk_score = sum(SIGNAL_WEIGHTS[signal.code] for signal in signals)
    if risk_score >= HIGH_RISK_THRESHOLD:
        risk_level = "high"
    elif risk_score >= MEDIUM_RISK_THRESHOLD:
        risk_level = "medium"
    else:
        risk_level = "low"

    return FraudAssessmentResult(risk_level=risk_level, risk_score=risk_score, signals=signals)
