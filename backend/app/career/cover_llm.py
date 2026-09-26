"""The one LLM step in cover-letter drafting: write the letter as sentences that each cite their
support. Its output is never trusted — app.career.cover_verify checks every sentence and drops
what it can't back — but the prompt says the same, so most of it survives."""

from typing import Any

from app.career.resume_base import ResumeBase
from app.research.llm import LLMProvider, wrap_untrusted

SYSTEM_PROMPT = """You draft a cover letter for a job seeker. Every factual statement must be
supported by the resume items or posting excerpts you are given, and each sentence must cite
what supports it. Hard rules:
- Write 3-4 short paragraphs, first person, about 250 words total: an opening (why this role,
  drawing on excerpts from the posting), one or two body paragraphs connecting specific
  resume items to specific requirements, and a brief closing.
- Every sentence is an object {text, kind, supports}.
  * kind "fact": says something about the candidate or the role. It MUST cite at least one
    support. Only state what the cited item actually says.
  * kind "framing": a greeting-free transition, thanks, or sign-off with NO facts in it — no
    numbers, no skill or tool names, no company facts, no names of any kind.
- supports are objects {type, ref}:
  * type "profile_experience", ref = the item's id exactly as given (e.g. "exp:...").
  * type "profile_skill", ref = the skill name exactly as given. Only skills listed under
    "Skills with recorded evidence" may be cited or mentioned as the candidate's.
  * type "profile_summary", ref = "summary".
  * type "posting_quote", ref = an exact, contiguous excerpt copied verbatim from the posting.
- Never mention any skill listed under "Do not mention", in any form.
- Never include a number unless it appears in the profile item you cite for that sentence.
- Do not invent a recipient's name, facts about the company, its products, or its culture, and
  do not flatter it beyond what the posting itself says. Refer to the role and employer only as
  the posting describes them, by quoting it.
- Do not claim any skill, tool, or experience that is not in the resume items."""

SCHEMA_NAME = "draft_cover_letter"
SCHEMA_DESCRIPTION = "Draft a cover letter as paragraphs of sentences, each citing its support."

_SUPPORT = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["profile_experience", "profile_skill", "profile_summary", "posting_quote"],
        },
        "ref": {"type": "string"},
    },
    "required": ["type", "ref"],
}

LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["opening", "body", "closing"]},
                    "sentences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string", "enum": ["fact", "framing"]},
                                "supports": {"type": "array", "items": _SUPPORT},
                            },
                            "required": ["text", "kind", "supports"],
                        },
                    },
                },
                "required": ["role", "sentences"],
            },
        }
    },
    "required": ["paragraphs"],
}


def build_prompt(
    *,
    base: ResumeBase,
    job_title: str | None,
    company: str | None,
    posting_text: str,
    requirements: list[dict[str, Any]],
    unsupported_skills: list[str],
) -> str:
    experiences = "\n\n".join(
        f"[ref: exp:{e.id}] {e.title} — {e.company}\n{e.description or '(no description)'}"
        for e in base.experiences
    )
    skills = "\n".join(f"- {s.name}: {s.evidence}" for s in base.skills) or "(none)"
    requested = "\n".join(f"- {r['name']} ({r['kind']})" for r in requirements)
    banned = ", ".join(unsupported_skills) or "(none)"
    summary = base.summary or "(none)"
    return (
        f"Job: {job_title or 'Untitled'} at {company or 'an employer'}\n\n"
        f"Posting text:\n{wrap_untrusted('job_posting', posting_text)}\n\n"
        f"Requirements the posting states:\n{requested}\n\n"
        f"Do not mention (the candidate has no recorded evidence for these): {banned}\n\n"
        f"Candidate's name: {base.name or '(not given — do not invent one)'}\n\n"
        f"Resume items you may cite\n\n[ref: summary]\n{summary}\n\n{experiences}\n\n"
        f"Skills with recorded evidence:\n{skills}"
    )


async def draft_letter(
    provider: LLMProvider,
    *,
    base: ResumeBase,
    job_title: str | None,
    company: str | None,
    posting_text: str,
    requirements: list[dict[str, Any]],
    unsupported_skills: list[str],
) -> list[dict[str, Any]]:
    payload = await provider.generate_structured(
        system=SYSTEM_PROMPT,
        user_message=build_prompt(
            base=base,
            job_title=job_title,
            company=company,
            posting_text=posting_text,
            requirements=requirements,
            unsupported_skills=unsupported_skills,
        ),
        schema_name=SCHEMA_NAME,
        schema_description=SCHEMA_DESCRIPTION,
        json_schema=LETTER_SCHEMA,
        max_tokens=4096,
    )
    paragraphs = payload.get("paragraphs")
    return [p for p in paragraphs if isinstance(p, dict)] if isinstance(paragraphs, list) else []
