"""Renders a stored WeeklyDigest to PDF bytes — pure formatting of already-computed facts, no
LLM, no live re-query (see app.reporting.service). Uses reportlab: pure Python, no system
dependencies, unlike an HTML/CSS renderer such as weasyprint (which needs the GTK/Pango/Cairo
native stack — a real pain on native Windows, which is what this backend runs on)."""

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from app.reporting.models import WeeklyDigest

_styles = getSampleStyleSheet()
_TITLE = _styles["Title"]
_HEADING = ParagraphStyle("DigestHeading", parent=_styles["Heading2"], spaceBefore=14, spaceAfter=6)
_BODY = _styles["BodyText"]
_MUTED = ParagraphStyle("DigestMuted", parent=_styles["BodyText"], textColor=colors.grey)


def _job_line(item: dict[str, Any]) -> str:
    title = item.get("title") or "Untitled posting"
    company = item.get("company_name")
    return f"{title} — {company}" if company else title


def _bullets(lines: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(line, _BODY)) for line in lines],
        bulletType="bullet",
        leftIndent=18,
    )


def _section(story: list[Any], title: str, lines: list[str], empty_text: str) -> None:
    story.append(Paragraph(title, _HEADING))
    if lines:
        story.append(_bullets(lines))
    else:
        story.append(Paragraph(empty_text, _MUTED))


def render_digest_pdf(digest: WeeklyDigest) -> bytes:
    data = digest.data
    period = data.get("period", {})
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    story: list[Any] = [
        Paragraph("Weekly Digest", _TITLE),
        Paragraph(
            f"{period.get('start', '?')} to {period.get('end', '?')} "
            f"&middot; generated {data.get('generated_at', '?')}",
            _MUTED,
        ),
        Spacer(1, 12),
    ]

    attention = data.get("attention", {})
    attention_lines: list[str] = []
    for item in attention.get("follow_ups_overdue", []):
        attention_lines.append(f"Follow-up overdue: {_job_line(item)}")
    for item in attention.get("follow_ups_due_today", []):
        attention_lines.append(f"Follow-up due today: {_job_line(item)}")
    for item in attention.get("stale_matches", []):
        attention_lines.append(f"Match is stale (profile changed since): {_job_line(item)}")
    for item in attention.get("stale_resumes", []):
        attention_lines.append(f"Tailored resume is stale: {_job_line(item)}")
    for item in attention.get("stale_cover_letters", []):
        attention_lines.append(f"Cover letter is stale: {_job_line(item)}")
    for item in attention.get("stalled_runs", []):
        kind = item.get("kind", "run")
        label = item.get("integration") if kind == "sync" else _job_line(item)
        kind_label = kind.replace("_", " ")
        attention_lines.append(f"A {kind_label} didn't finish and needs a retry: {label}")
    for name in attention.get("connections_needing_reauth", []):
        attention_lines.append(f"{name.capitalize()} needs to be reconnected")
    if attention.get("pending_audit_approvals", {}).get("count"):
        attention_lines.append(
            f"{attention['pending_audit_approvals']['count']} action(s) awaiting your approval"
        )
    pending_proposals = attention.get("pending_skill_proposals", {}).get("count")
    if pending_proposals:
        attention_lines.append(f"{pending_proposals} GitHub skill proposal(s) awaiting review")
    _section(
        story,
        "Needs your attention",
        attention_lines,
        "Nothing needs your attention right now.",
    )

    career = data.get("career", {})
    career_lines: list[str] = []
    if career.get("jobs_discovered", {}).get("count"):
        career_lines.append(f"{career['jobs_discovered']['count']} new job(s) discovered")
    if career.get("matches_computed", {}).get("count"):
        for m in career["matches_computed"]["items"]:
            percent = m.get("score_percent")
            score = f"{percent}%" if percent is not None else "not assessed"
            career_lines.append(f"Match computed for {_job_line(m)}: {score}")
    if career.get("high_risk_postings", {}).get("count"):
        for item in career["high_risk_postings"]["items"]:
            career_lines.append(f"High fraud risk flagged: {_job_line(item)}")
    by_status = career.get("application_status_changes", {}).get("by_status", {})
    for status, count in by_status.items():
        career_lines.append(f"{count} application(s) moved to '{status}'")
    if career.get("cover_letters_drafted", {}).get("count"):
        career_lines.append(f"{career['cover_letters_drafted']['count']} cover letter(s) drafted")
    if career.get("resumes_drafted", {}).get("count"):
        career_lines.append(f"{career['resumes_drafted']['count']} resume(s) tailored")
    if career.get("practice_sessions", {}).get("count"):
        tally = career["practice_sessions"]["verdict_tally"]
        career_lines.append(
            f"{career['practice_sessions']['count']} interview practice session(s) — "
            f"{tally['addressed']} addressed, {tally['partially_addressed']} partial, "
            f"{tally['missed']} missed, {tally['unclear']} unclear, "
            f"{tally['unanswered']} unanswered"
        )
    _section(story, "Career activity this week", career_lines, "No career activity this week.")

    research = data.get("research", {})
    research_lines: list[str] = []
    if research.get("queries_run", {}).get("count"):
        research_lines.append(
            f"{research['queries_run']['count']} research quer(y/ies) run, "
            f"{research.get('queries_completed', {}).get('count', 0)} completed"
        )
    claims_by_status = research.get("claims_added", {}).get("by_status", {})
    for status, count in claims_by_status.items():
        research_lines.append(f"{count} claim(s) added: {status}")
    _section(
        story, "Research activity this week", research_lines, "No research activity this week."
    )

    gmail = data.get("gmail", {})
    if gmail.get("connected"):
        gmail_lines = [
            f"{gmail['messages_synced']['count']} message(s) synced this week",
            f"{gmail['unread_count']} unread",
        ]
    else:
        gmail_lines = ["Gmail is not connected."]
    _section(story, "Gmail", gmail_lines, "")

    github = data.get("github", {})
    if github.get("connected"):
        github_lines = [
            f"{github['repos_synced']['count']} repo(s) synced this week",
            f"{github['pending_proposals']['count']} skill proposal(s) pending review",
            f"Readiness as of now: {github['readiness']['passed']} of "
            f"{github['readiness']['total']} checks passing",
        ]
    else:
        github_lines = ["GitHub is not connected."]
    _section(story, "GitHub", github_lines, "")

    calendar = data.get("calendar", {})
    calendar_lines: list[str] = []
    if calendar.get("connected"):
        for item in calendar.get("upcoming_interviews", []):
            job = item.get("job")
            calendar_lines.append(
                f"Interview: {item.get('summary') or (job and _job_line(job)) or 'Untitled'} "
                f"({item.get('start_at') or 'no time set'})"
            )
        for item in calendar.get("upcoming_deadlines", []):
            job = item.get("job")
            calendar_lines.append(
                f"Deadline: {item.get('summary') or (job and _job_line(job)) or 'Untitled'} "
                f"({item.get('start_at') or 'no time set'})"
            )
        empty = "No upcoming interviews or deadlines in the lookahead window."
    else:
        empty = "Calendar is not connected."
    _section(story, "Upcoming", calendar_lines, empty)

    doc.build(story)
    return buffer.getvalue()
