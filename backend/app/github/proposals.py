"""Deciding on skill-evidence proposals. This is the only place GitHub data reaches the profile,
and it happens only when the user accepts. Accepting is a Yellow action, so it goes through the
audit system's real workflow: what is proposed and why, the user's decision, then the result."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import decide_approval, record_result, request_approval
from app.career.matching import normalize_skill
from app.github.derive import contribution_from_dict, evidence_text
from app.github.models import GithubConnection, GithubSkillProposal
from app.profile.models import Profile, Skill, SkillVersion
from app.profile.skills import record_skill_version

KIND_CATEGORY = {"language": "Language", "framework": "Framework / library", "tool": "Tool"}


class ProposalStateError(RuntimeError):
    """The proposal was already decided."""


class LevelRequiredError(RuntimeError):
    """A new skill needs the user to choose a level: byte counts can't say how proficient
    someone is, so it's never guessed."""


def _preview(connection: GithubConnection, proposal: GithubSkillProposal) -> str:
    return evidence_text(
        connection.github_login,
        proposal.skill_name,
        [contribution_from_dict(c) for c in proposal.contributions],
    )


def preview_evidence(connection: GithubConnection, proposal: GithubSkillProposal) -> str:
    return _preview(connection, proposal)


async def _profile_and_skill(
    db: AsyncSession, user_id: uuid.UUID, skill_name: str
) -> tuple[Profile, Skill | None]:
    profile = (
        await db.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.flush()
    skills = (
        (
            await db.execute(
                select(Skill)
                .where(Skill.profile_id == profile.id)
                .options(selectinload(Skill.versions))
            )
        )
        .scalars()
        .all()
    )
    wanted = normalize_skill(skill_name)
    return profile, next((s for s in skills if normalize_skill(s.name) == wanted), None)


async def accept_proposal(
    db: AsyncSession,
    connection: GithubConnection,
    proposal: GithubSkillProposal,
    level: str | None,
) -> tuple[Skill, SkillVersion]:
    """Adds the evidence to the user's profile. An existing skill keeps its current level unless
    the user picks another; a new skill needs a level from the user."""
    if proposal.status != "pending":
        raise ProposalStateError(f"This proposal was already {proposal.status}.")

    profile, skill = await _profile_and_skill(db, connection.user_id, proposal.skill_name)
    previous_level = skill.versions[0].level if skill and skill.versions else None
    chosen = level or previous_level
    if chosen is None:
        raise LevelRequiredError(
            f"Choose your level for {proposal.skill_name}. GitHub data shows what you've built "
            "with it, not how proficient you are."
        )

    text = _preview(connection, proposal)
    contributions = [contribution_from_dict(c) for c in proposal.contributions]
    url = (contributions[0].source_url if contributions else None) or None
    audit = await request_approval(
        db,
        user_id=connection.user_id,
        action="github.skill_evidence.accept",
        risk_level="yellow",
        summary=f"Add GitHub evidence for {proposal.skill_name} to your profile at level {chosen}.",
        evidence={
            "skill": proposal.skill_name,
            "level": chosen,
            "level_carried_forward": level is None,
            "existing_skill": skill is not None,
            "attribution": proposal.attribution,
            "evidence_text": text,
            "repos": [c.repo for c in contributions],
        },
        resource_type="github_skill_proposal",
        resource_id=proposal.id,
    )
    await decide_approval(db, audit_log_id=audit.id, user_id=connection.user_id, approved=True)

    if skill is None:
        skill = Skill(
            profile_id=profile.id,
            name=proposal.skill_name,
            category=KIND_CATEGORY.get(proposal.kind),
            versions=[],
        )
        db.add(skill)
        await db.flush()
    version = await record_skill_version(
        db,
        profile_id=profile.id,
        skill=skill,
        level=chosen,
        evidence=text,
        evidence_url=url[:500] if url else None,
    )
    proposal.status = "accepted"
    proposal.decided_at = datetime.now(UTC)
    proposal.skill_version_id = version.id
    await record_result(
        db,
        audit_log_id=audit.id,
        result={
            "skill_id": str(skill.id),
            "skill_version_id": str(version.id),
            "previous_level": previous_level,
        },
    )
    await db.commit()
    return skill, version


async def dismiss_proposal(
    db: AsyncSession, connection: GithubConnection, proposal: GithubSkillProposal
) -> None:
    if proposal.status != "pending":
        raise ProposalStateError(f"This proposal was already {proposal.status}.")
    audit = await request_approval(
        db,
        user_id=connection.user_id,
        action="github.skill_evidence.accept",
        risk_level="yellow",
        summary=f"Add GitHub evidence for {proposal.skill_name} to your profile.",
        evidence={
            "skill": proposal.skill_name,
            "repos": [c["repo"] for c in proposal.contributions],
        },
        resource_type="github_skill_proposal",
        resource_id=proposal.id,
    )
    await decide_approval(db, audit_log_id=audit.id, user_id=connection.user_id, approved=False)
    proposal.status = "dismissed"
    proposal.decided_at = datetime.now(UTC)
    await db.commit()
