import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SkillLevel = Literal["beginner", "intermediate", "advanced", "expert"]
RemotePreference = Literal["remote", "hybrid", "onsite", "no_preference"]


class ProfileLinkCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)


class ProfileLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    url: str


class ProfileUpdate(BaseModel):
    headline: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    location: str | None = Field(default=None, max_length=255)


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    headline: str | None
    summary: str | None
    location: str | None
    links: list[ProfileLinkRead]
    created_at: datetime
    updated_at: datetime


class WorkExperienceCreate(BaseModel):
    company: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    start_date: date
    end_date: date | None = None
    description: str | None = None

    @model_validator(mode="after")
    def check_dates(self) -> "WorkExperienceCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class WorkExperienceUpdate(BaseModel):
    company: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None


class WorkExperienceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company: str
    title: str
    location: str | None
    start_date: date
    end_date: date | None
    description: str | None


class EducationCreate(BaseModel):
    institution: str = Field(min_length=1, max_length=255)
    degree: str | None = Field(default=None, max_length=255)
    field: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None


class EducationUpdate(BaseModel):
    institution: str | None = Field(default=None, max_length=255)
    degree: str | None = Field(default=None, max_length=255)
    field: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None


class EducationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution: str
    degree: str | None
    field: str | None
    start_date: date | None
    end_date: date | None


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)


class SkillVersionCreate(BaseModel):
    level: SkillLevel
    evidence: str = Field(
        min_length=10,
        max_length=4000,
        description="What backs this claim — a project, a role, a credential. Not a guess.",
    )
    evidence_url: str | None = Field(default=None, max_length=500)
    work_experience_id: uuid.UUID | None = None


class SkillVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    level: str
    evidence: str
    evidence_url: str | None
    work_experience_id: uuid.UUID | None
    asserted_at: datetime


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None
    created_at: datetime
    versions: list[SkillVersionRead]


class PreferencesUpdate(BaseModel):
    job_types: list[str] | None = None
    remote_preference: RemotePreference | None = None
    locations: list[str] | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    industries_include: list[str] | None = None
    industries_exclude: list[str] | None = None
    deal_breakers: str | None = None

    @model_validator(mode="after")
    def check_salary_range(self) -> "PreferencesUpdate":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min cannot be greater than salary_max")
        return self


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_types: list[str]
    remote_preference: str
    locations: list[str]
    salary_min: int | None
    salary_max: int | None
    industries_include: list[str]
    industries_exclude: list[str]
    deal_breakers: str | None
    updated_at: datetime
