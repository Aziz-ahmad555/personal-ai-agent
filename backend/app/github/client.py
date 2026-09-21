"""Read-only calls to the GitHub REST API. Only GET requests exist in this module; there is no
write helper to call by mistake."""

from typing import Any

import httpx

from app.github.oauth import GITHUB_API_URL

API_VERSION = "2022-11-28"


class GithubApiError(RuntimeError):
    """GitHub returned something we can't use (HTTP error, unexpected shape)."""


class GithubAuthError(GithubApiError):
    """GitHub rejected the token (401): expired, revoked or wrong."""


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }


async def _get(client: httpx.AsyncClient, access_token: str, path: str) -> dict[str, Any]:
    response = await client.get(f"{GITHUB_API_URL}{path}", headers=_headers(access_token))
    if response.status_code == 401:
        raise GithubAuthError("GitHub rejected the access token.")
    if response.status_code != 200:
        raise GithubApiError(f"GitHub returned HTTP {response.status_code} for {path}.")
    data = response.json()
    if not isinstance(data, dict):
        raise GithubApiError(f"GitHub returned an unexpected response for {path}.")
    return data


async def get_authenticated_user(client: httpx.AsyncClient, access_token: str) -> dict[str, Any]:
    """The account the token belongs to. Its login and id are what prove which GitHub account
    the user controls."""
    user = await _get(client, access_token, "/user")
    if not isinstance(user.get("login"), str) or not isinstance(user.get("id"), int):
        raise GithubApiError("GitHub's user response was missing a login or id.")
    return user


async def list_installations(client: httpx.AsyncClient, access_token: str) -> list[dict[str, Any]]:
    """Installations of this GitHub App that the user can reach, with the permissions each
    one holds. Empty when the app isn't installed anywhere (public data only)."""
    data = await _get(client, access_token, "/user/installations?per_page=100")
    installations = data.get("installations", [])
    if not isinstance(installations, list):
        raise GithubApiError("GitHub's installations response was not a list.")
    return [
        {
            "id": item.get("id"),
            "account": (item.get("account") or {}).get("login"),
            "repository_selection": item.get("repository_selection"),
            "permissions": item.get("permissions") or {},
        }
        for item in installations
        if isinstance(item, dict)
    ]
