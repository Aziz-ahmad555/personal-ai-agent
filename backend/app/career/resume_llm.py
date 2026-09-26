"""The one LLM step in resume tailoring: propose rewordings of existing profile text.

The model is a *rewriter*, not an author. It may rephrase and emphasize what an item already
says so it speaks to the posting's requirements, and nothing else. Its output is never trusted
— every proposal goes through app.career.resume_verify before a user sees it — but the prompt
says the same thing, so most proposals are usable rather than discarded.
"""

from dataclasses import dataclass
from typing import Any

from app.research.llm import LLMProvider, wrap_untrusted

SYSTEM_PROMPT = """You help a job seeker tailor their EXISTING resume text to one job posting.
You are an editor, not an author. Hard rules:
- Only rephrase and re-emphasize what each item's own text already says. Never add a fact,
  number, date, employer, title, tool, technology, skill, or outcome that is not already in
  that item's text.
- You may use a posting requirement's vocabulary only where the item's text already supports
  it (e.g. the item says "built REST services" and the posting says "API development").
- Do not mention any skill from the posting that the item's text doesn't already mention.
- Keep it concise and no longer than about 1.3x the original. Keep the original's voice.
- Propose a change only if it genuinely makes the item speak better to a listed requirement.
  If an item can't honestly be improved for this posting, leave it out entirely.
- For each change, name the requirement(s) it addresses, exactly as listed, and say in one
  sentence why the new wording is better for this posting."""

SCHEMA_NAME = "propose_resume_rewrites"
SCHEMA_DESCRIPTION = "Propose rewordings of existing resume items, tailored to a job posting."

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "The id of the item being rewritten, exactly as given.",
                    },
                    "new_text": {"type": "string", "description": "The reworded text."},
                    "addresses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Requirement names from the list, exactly as given.",
                    },
                    "rationale": {"type": "string", "description": "One sentence."},
                },
                "required": ["source_id", "new_text", "addresses", "rationale"],
            },
        }
    },
    "required": ["changes"],
}


@dataclass
class TailorItem:
    source_id: str
    label: str
    text: str


@dataclass
class RewriteProposal:
    source_id: str
    new_text: str
    addresses: list[str]
    rationale: str


def build_prompt(
    *,
    job_title: str | None,
    company: str | None,
    requirements: list[dict[str, Any]],
    items: list[TailorItem],
) -> str:
    req_lines = "\n".join(f"- {r['name']} ({r['kind']})" for r in requirements)
    item_blocks = "\n\n".join(
        f"[id: {item.source_id}] {item.label}\n{item.text}" for item in items
    )
    return (
        f"Job: {job_title or 'Untitled'} at {company or 'an employer'}\n\n"
        f"Requirements from the posting:\n{wrap_untrusted('job_requirements', req_lines)}\n\n"
        f"Resume items you may reword:\n\n{item_blocks}"
    )


async def propose_rewrites(
    provider: LLMProvider,
    *,
    job_title: str | None,
    company: str | None,
    requirements: list[dict[str, Any]],
    items: list[TailorItem],
) -> list[RewriteProposal]:
    payload = await provider.generate_structured(
        system=SYSTEM_PROMPT,
        user_message=build_prompt(
            job_title=job_title, company=company, requirements=requirements, items=items
        ),
        schema_name=SCHEMA_NAME,
        schema_description=SCHEMA_DESCRIPTION,
        json_schema=REWRITE_SCHEMA,
        max_tokens=4096,
    )
    proposals: list[RewriteProposal] = []
    for raw in payload.get("changes") or []:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or "").strip()
        new_text = str(raw.get("new_text") or "").strip()
        if not source_id or not new_text:
            continue
        addresses = [str(a).strip() for a in raw.get("addresses") or [] if str(a).strip()]
        proposals.append(
            RewriteProposal(
                source_id=source_id,
                new_text=new_text,
                addresses=addresses,
                rationale=str(raw.get("rationale") or "").strip(),
            )
        )
    return proposals
