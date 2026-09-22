import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PracticeStatus = Literal[
    "questions_running", "ready_for_answers", "feedback_running", "completed", "failed"
]
PracticeCategory = Literal["technical", "behavioral", "situational"]
PracticeRefType = Literal["posting_requirement", "profile_experience", "profile_skill"]
PracticeVerdict = Literal["addressed", "partially_addressed", "missed", "unclear"]


class PracticeQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    text: str
    category: PracticeCategory
    ref_type: PracticeRefType
    ref_name: str
    ref_excerpt: str
    answer_text: str | None
    answered_at: datetime | None
    verdict: PracticeVerdict | None
    feedback_text: str | None


class PracticeDroppedRead(BaseModel):
    question: str
    reason: str


class PracticeCounts(BaseModel):
    addressed: int = 0
    partially_addressed: int = 0
    missed: int = 0
    unclear: int = 0
    unanswered: int = 0


class PracticeSessionSummary(BaseModel):
    id: uuid.UUID
    status: PracticeStatus
    error: str | None
    started_at: datetime
    created_at: datetime
    question_count: int
    counts: PracticeCounts = PracticeCounts()


class PracticeSessionRead(BaseModel):
    id: uuid.UUID
    job_posting_id: uuid.UUID
    application_id: uuid.UUID | None
    status: PracticeStatus
    error: str | None
    started_at: datetime
    created_at: datetime
    questions: list[PracticeQuestionRead] = []
    # Questions the model proposed that couldn't be grounded, so were never shown: [{question,
    # reason}].
    dropped: list[PracticeDroppedRead] = []
    counts: PracticeCounts = PracticeCounts()


class StartPracticeSessionRequest(BaseModel):
    # Optional cross-link, e.g. "this session was for the Sept 30 interview" — must belong to
    # the same job and the same user.
    application_id: uuid.UUID | None = None


class PracticeAnswerInput(BaseModel):
    question_id: uuid.UUID
    # Empty (or omitted entirely) leaves/returns the question to unanswered.
    answer_text: str = Field(default="", max_length=4000)


class SubmitPracticeAnswersRequest(BaseModel):
    answers: list[PracticeAnswerInput]
