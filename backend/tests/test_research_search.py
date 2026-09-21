import types

import pytest

from app.research import search


def test_get_search_provider_fails_closed_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search, "get_settings", lambda: types.SimpleNamespace(tavily_api_key=None))

    with pytest.raises(search.SearchError):
        search.get_search_provider()


def test_get_search_provider_returns_provider_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search, "get_settings", lambda: types.SimpleNamespace(tavily_api_key="fake-key")
    )

    provider = search.get_search_provider()
    assert isinstance(provider, search.TavilySearchProvider)
