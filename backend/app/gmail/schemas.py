import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ConnectionStatus = Literal["connected", "needs_reauth", "disconnected"]
SyncRunStatus = Literal["pending", "running", "completed", "failed"]
SyncType = Literal["backfill", "incremental"]


class ConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    google_email: str
    status: ConnectionStatus
    last_synced_at: datetime | None
    last_sync_error: str | None
    created_at: datetime


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sync_type: SyncType
    status: SyncRunStatus
    messages_fetched: int
    messages_stored: int
    error: str | None
    started_at: datetime
    completed_at: datetime | None


class EmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    gmail_message_id: str
    thread_id: str
    subject: str | None
    from_address: str | None
    to_addresses: list[str]
    date: datetime | None
    snippet: str
    label_ids: list[str]


class DisconnectRequest(BaseModel):
    purge_data: bool
