"""The Gmail sync pipeline. Plain async code, not LangGraph — this is deterministic ETL
(list -> fetch -> store), not agentic reasoning, so a graph would be ceremony without
benefit. Mirrors app.research.pipeline's lifecycle discipline instead: a GmailSyncRun row
tracks pending/running/completed/failed exactly like ResearchQuery, so the frontend polls
it the same way, and a crash always resolves to a terminal state with a real error message
rather than leaving the row stuck at "running".

Two sync types:
- backfill: first-ever sync (or after a history cursor goes stale) — lists everything
  within the configured window (GMAIL_SYNC_WINDOW_DAYS) and fetches what we don't already
  have. Resumable: re-running a partial/failed backfill only fetches ids not yet stored.
- incremental: every sync after that — uses the Gmail History API from the last cursor,
  far cheaper than re-listing the whole window each time.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.gmail.client import (
    GmailApiError,
    GmailMessage,
    get_message,
    get_profile,
    list_history,
    list_message_ids,
)
from app.gmail.crypto import decrypt_token, encrypt_token
from app.gmail.models import EmailMessage, GmailConnection, GmailSyncRun
from app.gmail.oauth import ReauthRequiredError, refresh_access_token
from app.logging import get_logger

logger = get_logger(__name__)

GMAIL_QUERY_EXCLUDE = "-in:spam -in:trash"

# The background task lives inside the server process, so a restart silently kills it. A run
# still "pending"/"running" long after it started is reported as failed, detected on read —
# same idiom (and timeout) as app.calendar.sync.is_stalled / app.github.sync.is_stalled.
SYNC_TIMEOUT = timedelta(minutes=10)
STALLED_MESSAGE = (
    "This sync didn't finish — the server was probably restarted while it was running. Try again."
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_stalled(run: GmailSyncRun, *, now: datetime | None = None) -> bool:
    if run.status not in ("pending", "running"):
        return False
    return (now or datetime.now(UTC)) - _aware(run.started_at) > SYNC_TIMEOUT


def build_backfill_query(cutoff: datetime) -> str:
    return f"after:{cutoff.strftime('%Y/%m/%d')} {GMAIL_QUERY_EXCLUDE}"


async def ensure_valid_access_token(db: AsyncSession, connection: GmailConnection) -> str:
    """Returns a live access token, refreshing first if it's expired (or close to it).
    Sets the connection to needs_reauth and re-raises if the refresh token itself no
    longer works — expected roughly weekly while the OAuth consent screen stays in
    "Testing" status, not a bug."""
    if connection.access_token_encrypted is None or connection.refresh_token_encrypted is None:
        connection.status = "needs_reauth"
        await db.commit()
        raise ReauthRequiredError("Gmail is not connected.")

    now = datetime.now(UTC)
    if connection.token_expires_at and connection.token_expires_at > now + timedelta(minutes=2):
        return decrypt_token(connection.access_token_encrypted)

    refresh_token = decrypt_token(connection.refresh_token_encrypted)
    try:
        tokens = await refresh_access_token(refresh_token)
    except ReauthRequiredError:
        connection.status = "needs_reauth"
        await db.commit()
        raise

    connection.access_token_encrypted = encrypt_token(tokens.access_token)
    connection.token_expires_at = tokens.expires_at
    if tokens.granted_scopes:
        connection.granted_scopes = tokens.granted_scopes
    await db.commit()
    return tokens.access_token


async def _bounded_get(
    client: httpx.AsyncClient, access_token: str, message_id: str, semaphore: asyncio.Semaphore
) -> GmailMessage | None:
    async with semaphore:
        try:
            return await get_message(client, access_token, message_id)
        except GmailApiError as exc:
            # A message can vanish between list and get (deleted, moved) — skip it rather
            # than failing the whole sync over one race.
            logger.warning("gmail_message_fetch_failed", message_id=message_id, error=str(exc))
            return None


async def _existing_message_ids(
    db: AsyncSession, connection_id: uuid.UUID, candidate_ids: list[str]
) -> set[str]:
    if not candidate_ids:
        return set()
    rows = await db.execute(
        select(EmailMessage.gmail_message_id).where(
            EmailMessage.connection_id == connection_id,
            EmailMessage.gmail_message_id.in_(candidate_ids),
        )
    )
    return {row[0] for row in rows}


async def _fetch_and_store_new_messages(
    db: AsyncSession,
    client: httpx.AsyncClient,
    connection: GmailConnection,
    access_token: str,
    message_ids: list[str],
    sync_run: GmailSyncRun,
    settings: Settings,
) -> int:
    """Fetches (concurrently, bounded) and stores whichever of `message_ids` aren't
    already in our DB. Network fetches happen concurrently; DB writes happen sequentially
    afterward — AsyncSession isn't safe to use from multiple coroutines at once."""
    unique_ids = list(dict.fromkeys(message_ids))
    existing_ids = await _existing_message_ids(db, connection.id, unique_ids)
    new_ids = [i for i in unique_ids if i not in existing_ids]

    semaphore = asyncio.Semaphore(settings.gmail_fetch_concurrency)
    stored = 0
    batch_size = settings.gmail_fetch_concurrency

    for start in range(0, len(new_ids), batch_size):
        batch = new_ids[start : start + batch_size]
        results = await asyncio.gather(
            *[_bounded_get(client, access_token, message_id, semaphore) for message_id in batch]
        )
        for message in results:
            if message is None:
                continue
            db.add(
                EmailMessage(
                    connection_id=connection.id,
                    gmail_message_id=message.gmail_message_id,
                    thread_id=message.thread_id,
                    subject=message.subject,
                    from_address=message.from_address,
                    to_addresses=message.to_addresses,
                    date=message.date,
                    snippet=message.snippet,
                    body_text=message.body_text,
                    label_ids=message.label_ids,
                )
            )
            stored += 1
        sync_run.messages_stored = stored
        await db.commit()

    return stored


async def _update_history_cursor(
    db: AsyncSession, client: httpx.AsyncClient, connection: GmailConnection, access_token: str
) -> None:
    """Best-effort: if this fails even after client.py's own retries, the sync still
    succeeded at what matters (messages are stored) — it just falls back to a full
    backfill next time instead of a cheap incremental one, rather than losing the run."""
    try:
        profile = await get_profile(client, access_token)
    except GmailApiError as exc:
        logger.warning("gmail_history_cursor_update_failed", error=str(exc))
        return
    history_id = profile.get("historyId")
    if history_id:
        connection.last_history_id = str(history_id)
        await db.commit()


async def _run_backfill(
    db: AsyncSession,
    client: httpx.AsyncClient,
    connection: GmailConnection,
    access_token: str,
    sync_run: GmailSyncRun,
    settings: Settings,
) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=settings.gmail_sync_window_days)
    query = build_backfill_query(cutoff)

    all_ids: list[str] = []
    page_token: str | None = None
    while True:
        ids, page_token = await list_message_ids(
            client, access_token, query=query, page_token=page_token
        )
        all_ids.extend(ids)
        sync_run.messages_fetched = len(all_ids)
        await db.commit()
        if not page_token:
            break

    await _fetch_and_store_new_messages(
        db, client, connection, access_token, all_ids, sync_run, settings
    )

    await _update_history_cursor(db, client, connection, access_token)


async def _run_incremental(
    db: AsyncSession,
    client: httpx.AsyncClient,
    connection: GmailConnection,
    access_token: str,
    sync_run: GmailSyncRun,
    settings: Settings,
) -> bool:
    """Returns True if Gmail no longer has the stored history cursor (only ~1 week is
    retained) — the caller should fall back to a fresh backfill in that case."""
    assert connection.last_history_id is not None
    all_ids: list[str] = []
    page_token: str | None = None

    while True:
        ids, page_token, too_old = await list_history(
            client, access_token, start_history_id=connection.last_history_id, page_token=page_token
        )
        if too_old:
            connection.last_history_id = None
            await db.commit()
            return True
        all_ids.extend(ids)
        if not page_token:
            break

    sync_run.messages_fetched = len(all_ids)
    await db.commit()

    await _fetch_and_store_new_messages(
        db, client, connection, access_token, all_ids, sync_run, settings
    )

    await _update_history_cursor(db, client, connection, access_token)

    return False


async def run_sync(db: AsyncSession, sync_run_id: uuid.UUID) -> None:
    sync_run = await db.get(GmailSyncRun, sync_run_id)
    if sync_run is None:
        logger.warning("gmail_sync_run_not_found", sync_run_id=str(sync_run_id))
        return

    sync_run.status = "running"
    await db.commit()

    connection = await db.get(GmailConnection, sync_run.connection_id)
    if connection is None:
        sync_run.status = "failed"
        sync_run.error = "Gmail connection no longer exists."
        sync_run.completed_at = datetime.now(UTC)
        await db.commit()
        return

    settings = get_settings()
    error: str | None = None
    try:
        access_token = await ensure_valid_access_token(db, connection)
        async with httpx.AsyncClient(timeout=settings.gmail_fetch_timeout_seconds) as client:
            if connection.last_history_id is None:
                sync_run.sync_type = "backfill"
                await db.commit()
                await _run_backfill(db, client, connection, access_token, sync_run, settings)
            else:
                fell_back = await _run_incremental(
                    db, client, connection, access_token, sync_run, settings
                )
                if fell_back:
                    sync_run.sync_type = "backfill"
                    await db.commit()
                    await _run_backfill(db, client, connection, access_token, sync_run, settings)
        connection.status = "connected"
        connection.last_synced_at = datetime.now(UTC)
        connection.last_sync_error = None
    except ReauthRequiredError as exc:
        error = str(exc)
    except Exception as exc:  # last-resort guardrail: a crash must still resolve the run
        logger.exception("gmail_sync_crashed", sync_run_id=str(sync_run_id))
        error = f"Unexpected error: {exc}"

    if error:
        connection.last_sync_error = error
    sync_run.status = "failed" if error else "completed"
    sync_run.error = error
    sync_run.completed_at = datetime.now(UTC)
    await db.commit()
