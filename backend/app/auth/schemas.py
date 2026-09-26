import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccountDeletionResult(BaseModel):
    """The result of deciding a pending account.delete_all_data approval. A decline leaves
    everything untouched (deleted=False, nothing else set). An approval executes the
    deletion in the same call — see app.auth.account_deletion."""

    deleted: bool
    row_counts: dict[str, int] | None = None
    revoked_at_provider: dict[str, bool] | None = None
