import types

import pytest

from app.gmail import crypto


async def test_encrypt_decrypt_round_trips() -> None:
    crypto._get_fernet.cache_clear()
    encrypted = crypto.encrypt_token("ya29.some-real-looking-access-token")
    assert encrypted != "ya29.some-real-looking-access-token"
    assert crypto.decrypt_token(encrypted) == "ya29.some-real-looking-access-token"


async def test_decrypt_garbage_raises_unavailable_error() -> None:
    crypto._get_fernet.cache_clear()
    with pytest.raises(crypto.TokenEncryptionUnavailableError):
        crypto.decrypt_token("not-a-real-encrypted-token")


async def test_missing_key_raises_unavailable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    crypto._get_fernet.cache_clear()
    monkeypatch.setattr(
        crypto, "get_settings", lambda: types.SimpleNamespace(token_encryption_key=None)
    )
    with pytest.raises(crypto.TokenEncryptionUnavailableError):
        crypto.encrypt_token("some-token")
    crypto._get_fernet.cache_clear()
