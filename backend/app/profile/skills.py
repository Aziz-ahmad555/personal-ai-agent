"""Shared skill-version writing, so anything that adds evidence to a skill (the profile API, the
GitHub evidence proposals) goes through one path and the embedding never gets skipped."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.embeddings import sync_embedding
from app.profile.models import Skill, SkillVersion


async def record_skill_version(
    db: AsyncSession,
    *,
    profile_id: uuid.UUID,
    skill: Skill,
    level: str,
    evidence: str,
    evidence_url: str | None = None,
    work_experience_id: uuid.UUID | None = None,
) -> SkillVersion:
    """Adds a version (the skill's history is append-only) and embeds its evidence. Flushes but
    does not commit, so the caller decides what else belongs in the same transaction."""
    version = SkillVersion(
        skill_id=skill.id,
        level=level,
        evidence=evidence,
        evidence_url=evidence_url,
        work_experience_id=work_experience_id,
    )
    db.add(version)
    await db.flush()
    await sync_embedding(
        db,
        profile_id=profile_id,
        owner_type="skill_evidence",
        owner_id=version.id,
        text=f"{skill.name} ({version.level}): {version.evidence}",
    )
    return version
