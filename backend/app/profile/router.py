import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.profile.embeddings import delete_embedding, sync_embedding
from app.profile.models import (
    Education,
    Preferences,
    Profile,
    ProfileLink,
    Skill,
    SkillVersion,
    WorkExperience,
)
from app.profile.schemas import (
    EducationCreate,
    EducationRead,
    EducationUpdate,
    PreferencesRead,
    PreferencesUpdate,
    ProfileLinkCreate,
    ProfileLinkRead,
    ProfileRead,
    ProfileUpdate,
    SkillCreate,
    SkillRead,
    SkillVersionCreate,
    SkillVersionRead,
    WorkExperienceCreate,
    WorkExperienceRead,
    WorkExperienceUpdate,
)

router = APIRouter(prefix="/profile", tags=["profile"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _get_or_create_profile(db: AsyncSession, user: User) -> Profile:
    result = await db.execute(
        select(Profile).where(Profile.user_id == user.id).options(selectinload(Profile.links))
    )
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile

    profile = Profile(user_id=user.id)
    db.add(profile)
    await db.flush()
    await db.refresh(profile, attribute_names=["links"])
    return profile


async def _get_or_create_preferences(db: AsyncSession, user: User) -> Preferences:
    result = await db.execute(select(Preferences).where(Preferences.user_id == user.id))
    preferences = result.scalar_one_or_none()
    if preferences is not None:
        return preferences

    preferences = Preferences(user_id=user.id)
    db.add(preferences)
    await db.flush()
    return preferences


async def _get_owned_experience(
    db: AsyncSession, experience_id: uuid.UUID, profile_id: uuid.UUID
) -> WorkExperience:
    result = await db.execute(
        select(WorkExperience).where(
            WorkExperience.id == experience_id, WorkExperience.profile_id == profile_id
        )
    )
    experience = result.scalar_one_or_none()
    if experience is None:
        raise _NOT_FOUND
    return experience


async def _get_owned_education(
    db: AsyncSession, education_id: uuid.UUID, profile_id: uuid.UUID
) -> Education:
    result = await db.execute(
        select(Education).where(Education.id == education_id, Education.profile_id == profile_id)
    )
    education = result.scalar_one_or_none()
    if education is None:
        raise _NOT_FOUND
    return education


async def _get_owned_skill(db: AsyncSession, skill_id: uuid.UUID, profile_id: uuid.UUID) -> Skill:
    result = await db.execute(
        select(Skill)
        .where(Skill.id == skill_id, Skill.profile_id == profile_id)
        .options(selectinload(Skill.versions))
    )
    skill = result.scalar_one_or_none()
    if skill is None:
        raise _NOT_FOUND
    return skill


# --- Profile ---


@router.get("", response_model=ProfileRead)
async def get_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Profile:
    profile = await _get_or_create_profile(db, current_user)
    await db.commit()
    return profile


@router.put("", response_model=ProfileRead)
async def update_profile(
    payload: ProfileUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Profile:
    profile = await _get_or_create_profile(db, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.flush()

    bio_text = " ".join(filter(None, [profile.headline, profile.summary]))
    await sync_embedding(
        db, profile_id=profile.id, owner_type="bio", owner_id=profile.id, text=bio_text
    )

    await db.commit()
    await db.refresh(profile, attribute_names=["updated_at"])
    return profile


@router.post("/links", response_model=ProfileLinkRead, status_code=status.HTTP_201_CREATED)
async def add_link(
    payload: ProfileLinkCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileLink:
    profile = await _get_or_create_profile(db, current_user)
    link = ProfileLink(profile_id=profile.id, **payload.model_dump())
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    profile = await _get_or_create_profile(db, current_user)
    result = await db.execute(
        select(ProfileLink).where(ProfileLink.id == link_id, ProfileLink.profile_id == profile.id)
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise _NOT_FOUND
    await db.delete(link)
    await db.commit()


# --- Work experience ---


@router.get("/experience", response_model=list[WorkExperienceRead])
async def list_experience(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkExperience]:
    profile = await _get_or_create_profile(db, current_user)
    result = await db.execute(
        select(WorkExperience)
        .where(WorkExperience.profile_id == profile.id)
        .order_by(WorkExperience.start_date.desc())
    )
    await db.commit()
    return list(result.scalars())


@router.post("/experience", response_model=WorkExperienceRead, status_code=status.HTTP_201_CREATED)
async def create_experience(
    payload: WorkExperienceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkExperience:
    profile = await _get_or_create_profile(db, current_user)
    experience = WorkExperience(profile_id=profile.id, **payload.model_dump())
    db.add(experience)
    await db.flush()

    await sync_embedding(
        db,
        profile_id=profile.id,
        owner_type="work_experience",
        owner_id=experience.id,
        text=experience.description,
    )
    await db.commit()
    await db.refresh(experience)
    return experience


@router.put("/experience/{experience_id}", response_model=WorkExperienceRead)
async def update_experience(
    experience_id: uuid.UUID,
    payload: WorkExperienceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkExperience:
    profile = await _get_or_create_profile(db, current_user)
    experience = await _get_owned_experience(db, experience_id, profile.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(experience, field, value)
    await db.flush()

    await sync_embedding(
        db,
        profile_id=profile.id,
        owner_type="work_experience",
        owner_id=experience.id,
        text=experience.description,
    )
    await db.commit()
    await db.refresh(experience)
    return experience


@router.delete("/experience/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experience(
    experience_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    profile = await _get_or_create_profile(db, current_user)
    experience = await _get_owned_experience(db, experience_id, profile.id)
    await delete_embedding(db, owner_type="work_experience", owner_id=experience.id)
    await db.delete(experience)
    await db.commit()


# --- Education ---


@router.get("/education", response_model=list[EducationRead])
async def list_education(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Education]:
    profile = await _get_or_create_profile(db, current_user)
    result = await db.execute(select(Education).where(Education.profile_id == profile.id))
    await db.commit()
    return list(result.scalars())


def _education_text(education: Education) -> str:
    return " ".join(filter(None, [education.degree, education.field, education.institution]))


@router.post("/education", response_model=EducationRead, status_code=status.HTTP_201_CREATED)
async def create_education(
    payload: EducationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Education:
    profile = await _get_or_create_profile(db, current_user)
    education = Education(profile_id=profile.id, **payload.model_dump())
    db.add(education)
    await db.flush()

    await sync_embedding(
        db,
        profile_id=profile.id,
        owner_type="education",
        owner_id=education.id,
        text=_education_text(education),
    )
    await db.commit()
    await db.refresh(education)
    return education


@router.put("/education/{education_id}", response_model=EducationRead)
async def update_education(
    education_id: uuid.UUID,
    payload: EducationUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Education:
    profile = await _get_or_create_profile(db, current_user)
    education = await _get_owned_education(db, education_id, profile.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(education, field, value)
    await db.flush()

    await sync_embedding(
        db,
        profile_id=profile.id,
        owner_type="education",
        owner_id=education.id,
        text=_education_text(education),
    )
    await db.commit()
    await db.refresh(education)
    return education


@router.delete("/education/{education_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(
    education_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    profile = await _get_or_create_profile(db, current_user)
    education = await _get_owned_education(db, education_id, profile.id)
    await delete_embedding(db, owner_type="education", owner_id=education.id)
    await db.delete(education)
    await db.commit()


# --- Skills + version history ---


@router.get("/skills", response_model=list[SkillRead])
async def list_skills(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Skill]:
    profile = await _get_or_create_profile(db, current_user)
    result = await db.execute(
        select(Skill).where(Skill.profile_id == profile.id).options(selectinload(Skill.versions))
    )
    await db.commit()
    return list(result.scalars())


@router.post("/skills", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Skill:
    profile = await _get_or_create_profile(db, current_user)
    skill = Skill(profile_id=profile.id, **payload.model_dump())
    db.add(skill)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Skill '{payload.name}' already exists"
        ) from exc
    await db.refresh(skill, attribute_names=["versions"])
    return skill


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    profile = await _get_or_create_profile(db, current_user)
    skill = await _get_owned_skill(db, skill_id, profile.id)
    for version in skill.versions:
        await delete_embedding(db, owner_type="skill_evidence", owner_id=version.id)
    await db.delete(skill)
    await db.commit()


@router.get("/skills/{skill_id}/versions", response_model=list[SkillVersionRead])
async def list_skill_versions(
    skill_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SkillVersion]:
    profile = await _get_or_create_profile(db, current_user)
    skill = await _get_owned_skill(db, skill_id, profile.id)
    await db.commit()
    return skill.versions


@router.post(
    "/skills/{skill_id}/versions",
    response_model=SkillVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_skill_version(
    skill_id: uuid.UUID,
    payload: SkillVersionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SkillVersion:
    profile = await _get_or_create_profile(db, current_user)
    skill = await _get_owned_skill(db, skill_id, profile.id)

    if payload.work_experience_id is not None:
        await _get_owned_experience(db, payload.work_experience_id, profile.id)

    version = SkillVersion(skill_id=skill.id, **payload.model_dump())
    db.add(version)
    await db.flush()

    await sync_embedding(
        db,
        profile_id=profile.id,
        owner_type="skill_evidence",
        owner_id=version.id,
        text=f"{skill.name} ({version.level}): {version.evidence}",
    )
    await db.commit()
    await db.refresh(version)
    return version


# --- Preferences ---


@router.get("/preferences", response_model=PreferencesRead)
async def get_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Preferences:
    preferences = await _get_or_create_preferences(db, current_user)
    await db.commit()
    return preferences


def _preferences_text(preferences: Preferences) -> str:
    parts: list[str] = []
    if preferences.job_types:
        parts.append(f"Job types: {', '.join(preferences.job_types)}")
    parts.append(f"Remote preference: {preferences.remote_preference}")
    if preferences.locations:
        parts.append(f"Locations: {', '.join(preferences.locations)}")
    if preferences.salary_min is not None or preferences.salary_max is not None:
        low = preferences.salary_min if preferences.salary_min is not None else "?"
        high = preferences.salary_max if preferences.salary_max is not None else "?"
        parts.append(f"Salary range: {low}-{high}")
    if preferences.industries_include:
        parts.append(f"Interested industries: {', '.join(preferences.industries_include)}")
    if preferences.industries_exclude:
        parts.append(f"Excluded industries: {', '.join(preferences.industries_exclude)}")
    if preferences.deal_breakers:
        parts.append(f"Deal breakers: {preferences.deal_breakers}")
    return ". ".join(parts)


@router.put("/preferences", response_model=PreferencesRead)
async def update_preferences(
    payload: PreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Preferences:
    preferences = await _get_or_create_preferences(db, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(preferences, field, value)
    await db.flush()

    # Preferences has no direct link to Profile, but ProfileEmbedding rows require a
    # profile_id (for cascade-delete grouping) — fetch/create it purely for that FK.
    profile = await _get_or_create_profile(db, current_user)
    await sync_embedding(
        db,
        profile_id=profile.id,
        owner_type="preferences",
        owner_id=preferences.id,
        text=_preferences_text(preferences),
    )

    await db.commit()
    await db.refresh(preferences)
    return preferences
