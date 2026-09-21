"""LLM-assisted structured extraction of job-posting fields from raw text (a pasted
description or a fetched page's extracted content). Mirrors app.research.extraction: the
model returns only fields explicitly present in the text — required-field-only JSON
schema, so an unstated field is simply absent from the payload rather than filled with a
guessed or nullable-typed placeholder (CLAUDE.md: "if evidence isn't available, the system
says I don't know — it never fills a gap with a guess")."""

from dataclasses import dataclass

from app.research.llm import LLMProvider

SYSTEM_PROMPT = """You extract structured job-posting fields from raw text for a personal
job-search agent. Only record a field if it is explicitly stated in the text — copy values
as stated, never editorialize or summarize. Never guess, infer, or estimate a salary,
location, or company name that isn't written there: omit the field entirely instead.
remote_type is the one required field; use "unknown" for it if the text doesn't say."""

SCHEMA_NAME = "record_job_posting"
SCHEMA_DESCRIPTION = "Record structured fields extracted from a job posting's text."

JOB_POSTING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Job title exactly as stated. Omit if not stated.",
        },
        "company_name": {
            "type": "string",
            "description": "Employer name exactly as stated. Omit if not stated.",
        },
        "location": {
            "type": "string",
            "description": "Location exactly as stated. Omit if not stated.",
        },
        "remote_type": {
            "type": "string",
            "enum": ["remote", "hybrid", "onsite", "unknown"],
            "description": "unknown if the text doesn't say.",
        },
        "salary_min": {"type": "integer", "description": "Omit if no salary is stated."},
        "salary_max": {"type": "integer", "description": "Omit if no salary is stated."},
        "salary_currency": {
            "type": "string",
            "description": "e.g. 'USD'. Omit if no salary is stated.",
        },
    },
    "required": ["remote_type"],
}


@dataclass
class ExtractedJobFields:
    title: str | None
    company_name: str | None
    location: str | None
    remote_type: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None


async def extract_job_fields(provider: LLMProvider, *, raw_text: str) -> ExtractedJobFields:
    payload = await provider.generate_structured(
        system=SYSTEM_PROMPT,
        user_message=f"Job posting text:\n\n{raw_text}",
        schema_name=SCHEMA_NAME,
        schema_description=SCHEMA_DESCRIPTION,
        json_schema=JOB_POSTING_SCHEMA,
        max_tokens=1024,
    )
    return ExtractedJobFields(
        title=payload.get("title") or None,
        company_name=payload.get("company_name") or None,
        location=payload.get("location") or None,
        remote_type=payload.get("remote_type") or "unknown",
        salary_min=payload.get("salary_min"),
        salary_max=payload.get("salary_max"),
        salary_currency=payload.get("salary_currency") or None,
    )
