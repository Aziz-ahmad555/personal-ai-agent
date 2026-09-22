"""The two LLM steps in interview practice: write questions grounded in the posting's verified
requirements or the profile's recorded evidence, then — after the user answers — write feedback
grounded in the question's own quote/evidence and the user's own answer text. Neither output is
trusted as given: app.career.practice_verify resolves and checks every question and every
feedback item, the same discipline app.career.cover_verify applies to cover-letter sentences."""

from typing import Any

from app.career.resume_base import ResumeBase
from app.research.llm import LLMProvider

QUESTIONS_SYSTEM_PROMPT = """You write interview-practice questions for a job seeker, grounded
only in what you're given. Rules:
- Write 5 to 8 questions, a mix of technical, behavioral, and situational categories.
- Each question is an object {text, category, ref_type, ref}.
  * category is one of "technical", "behavioral", "situational".
  * ref_type is one of "posting_requirement", "profile_experience", "profile_skill" — what
    grounds the question.
  * ref_type "posting_requirement": ref = the requirement's name exactly as given.
  * ref_type "profile_experience": ref = the item's id exactly as given (e.g. "exp:...").
  * ref_type "profile_skill": ref = the skill name exactly as given. Only skills listed under
    "Skills with recorded evidence" may be used this way.
- Prefer covering as many distinct requirements as the question count allows; fill any
  remaining slots with questions grounded in a specific profile experience or skill.
- Ask the kind of question a real interviewer would ask about that requirement or experience —
  not a restatement of the requirement itself, and not a yes/no question.
- Never invent a requirement, skill, or experience beyond what's given to you."""

QUESTIONS_SCHEMA_NAME = "generate_practice_questions"
QUESTIONS_SCHEMA_DESCRIPTION = (
    "Write interview-practice questions, each grounded in a given requirement or profile item."
)

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["technical", "behavioral", "situational"],
                    },
                    "ref_type": {
                        "type": "string",
                        "enum": ["posting_requirement", "profile_experience", "profile_skill"],
                    },
                    "ref": {"type": "string"},
                },
                "required": ["text", "category", "ref_type", "ref"],
            },
        }
    },
    "required": ["questions"],
}


def _build_questions_prompt(
    *,
    job_title: str | None,
    company: str | None,
    requirements: list[dict[str, Any]],
    base: ResumeBase,
) -> str:
    requested = "\n".join(f"- {r['name']} ({r['kind']})" for r in requirements) or "(none)"
    experiences = "\n\n".join(
        f"[ref: exp:{e.id}] {e.title} — {e.company}\n{e.description or '(no description)'}"
        for e in base.experiences
    ) or "(none)"
    skills = "\n".join(f"- {s.name}: {s.evidence}" for s in base.skills) or "(none)"
    return (
        f"Job: {job_title or 'Untitled'} at {company or 'an employer'}\n\n"
        f"Requirements the posting states:\n{requested}\n\n"
        f"Profile experiences you may ground a question in:\n\n{experiences}\n\n"
        f"Skills with recorded evidence:\n{skills}"
    )


async def generate_questions(
    provider: LLMProvider,
    *,
    job_title: str | None,
    company: str | None,
    requirements: list[dict[str, Any]],
    base: ResumeBase,
) -> list[dict[str, Any]]:
    payload = await provider.generate_structured(
        system=QUESTIONS_SYSTEM_PROMPT,
        user_message=_build_questions_prompt(
            job_title=job_title, company=company, requirements=requirements, base=base
        ),
        schema_name=QUESTIONS_SCHEMA_NAME,
        schema_description=QUESTIONS_SCHEMA_DESCRIPTION,
        json_schema=QUESTIONS_SCHEMA,
        max_tokens=3072,
    )
    questions = payload.get("questions")
    return [q for q in questions if isinstance(q, dict)] if isinstance(questions, list) else []


FEEDBACK_SYSTEM_PROMPT = """You give feedback on interview-practice answers, for a job seeker.
You are given, for each question: its text, what it was grounded in (a posting requirement's
quote, or a profile experience/skill's evidence text), and the candidate's actual answer. Rules:
- For each question, return {question_id, verdict, rationale}.
- verdict is one of "addressed", "partially_addressed", "missed", "unclear" — "unclear" is for
  an answer too vague or off-topic to judge, not a synonym for "missed".
- rationale must reference ONLY what the given quote/evidence says and what the candidate's
  answer actually says. Never claim the candidate has experience, a skill, or a number that
  isn't literally in their answer text, even if the requirement or evidence mentions it.
- Do not soften or invent encouragement not grounded in the answer — be accurate, not kind.
- Keep each rationale to one or two sentences."""

FEEDBACK_SCHEMA_NAME = "generate_practice_feedback"
FEEDBACK_SCHEMA_DESCRIPTION = (
    "Give per-question feedback on interview-practice answers, citing only what was given."
)

FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "feedback": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["addressed", "partially_addressed", "missed", "unclear"],
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["question_id", "verdict", "rationale"],
            },
        }
    },
    "required": ["feedback"],
}


def _build_feedback_prompt(items: list[dict[str, Any]]) -> str:
    blocks = []
    for item in items:
        blocks.append(
            f"[question_id: {item['id']}]\n"
            f"Question: {item['text']}\n"
            f"Grounded in ({item['ref_type']}): {item['ref_excerpt']}\n"
            f"Candidate's answer: {item['answer_text']}"
        )
    return "\n\n".join(blocks)


async def generate_feedback(
    provider: LLMProvider, *, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    payload = await provider.generate_structured(
        system=FEEDBACK_SYSTEM_PROMPT,
        user_message=_build_feedback_prompt(items),
        schema_name=FEEDBACK_SCHEMA_NAME,
        schema_description=FEEDBACK_SCHEMA_DESCRIPTION,
        json_schema=FEEDBACK_SCHEMA,
        max_tokens=3072,
    )
    feedback = payload.get("feedback")
    return [f for f in feedback if isinstance(f, dict)] if isinstance(feedback, list) else []
