import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ConnectionStatus = Literal["connected", "needs_reauth", "disconnected"]


class ConnectionRead(BaseModel):
    """Deliberately has no token fields: nothing an API client can ask for returns a credential."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    google_email: str
    status: ConnectionStatus
    last_error: str | None
    created_at: datetime


class DisconnectResult(BaseModel):
    connection: ConnectionRead
    # Whether Google confirmed the token was revoked. False means it was only cleared locally
    # (Google was unreachable or refused); it will still expire on its own.
    revoked_at_google: bool
