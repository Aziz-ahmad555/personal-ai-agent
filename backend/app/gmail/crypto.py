"""Encrypts Gmail OAuth tokens before they touch the database. These are live credentials
to a real inbox — a DB dump or backup leak must not hand over working Gmail access, so they
get application-layer encryption on top of whatever the database's own storage provides."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class TokenEncryptionUnavailableError(RuntimeError):
    """Raised when TOKEN_ENCRYPTION_KEY is missing — this is not optional the way, say,
    Voyage embeddings are: without it we refuse to store or read Gmail tokens at all,
    rather than falling back to storing them in plaintext."""


@lru_cache
def _get_fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise TokenEncryptionUnavailableError(
            "TOKEN_ENCRYPTION_KEY is not set — cannot encrypt/decrypt Gmail tokens. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt_token(plain_token: str) -> str:
    return _get_fernet().encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted_token.encode()).decode()
    except InvalidToken as exc:
        raise TokenEncryptionUnavailableError(
            "Stored Gmail token could not be decrypted — TOKEN_ENCRYPTION_KEY may have "
            "changed since it was stored. Reconnect Gmail."
        ) from exc
