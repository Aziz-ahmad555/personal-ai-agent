"""Read-only calls to the GitHub REST API. Only GET requests exist in this module; there is no
write helper to call by mistake."""

import asyncio
import base64
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.github.oauth import GITHUB_API_URL

API_VERSION = "2022-11-28"

# Rate limits are shared across everything this app does with the token, so calls are counted and
# capped per sync, and waits are bounded so a sync never sits for minutes on a limit.
MAX_ATTEMPTS = 3
MAX_WAIT_SECONDS = 30.0
MAX_FILE_BYTES = 200_000
MAX_REPO_PAGES = 5


class GithubApiError(RuntimeError):
    """GitHub returned something we can't use (HTTP error, unexpected shape)."""


class GithubAuthError(GithubApiError):
    """GitHub rejected the token (401): expired, revoked or wrong."""


class RateLimitedError(GithubApiError):
    """GitHub is rate limiting and asked us to wait longer than we're willing to."""


class RequestBudgetExceededError(GithubApiError):
    """This sync used up its request allowance."""


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


# --- a counted, rate-limit-aware session ----------------------------------------------------


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


class GithubHttp:
    """GET requests with a budget, retries on server errors, and bounded waits on rate limits."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        *,
        budget: int = 300,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._token = access_token
        self._budget = budget
        self._sleep = sleep or _pause
        self.requests_made = 0

    async def get(self, path: str, *, allow: tuple[int, ...] = ()) -> httpx.Response:
        """The response for a 200 or any status in `allow` (for expected answers like 404)."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.requests_made >= self._budget:
                raise RequestBudgetExceededError(
                    f"Stopped after {self.requests_made} requests, this sync's limit."
                )
            self.requests_made += 1
            response = await self._client.get(
                f"{GITHUB_API_URL}{path}", headers=_headers(self._token)
            )
            status = response.status_code
            if status == 200 or status in allow:
                return response
            if status == 401:
                raise GithubAuthError("GitHub rejected the access token.")
            wait = self._rate_limit_wait(response)
            if wait is not None:
                if wait > MAX_WAIT_SECONDS:
                    raise RateLimitedError(
                        f"GitHub is rate limiting this token; it asked us to wait {int(wait)}s."
                    )
                if attempt < MAX_ATTEMPTS:
                    await self._sleep(wait)
                    continue
                raise RateLimitedError("GitHub kept rate limiting this token.")
            if status >= 500 and attempt < MAX_ATTEMPTS:
                await self._sleep(2.0 ** (attempt - 1))
                continue
            raise GithubApiError(f"GitHub returned HTTP {status} for {path}.")
        raise GithubApiError(f"GitHub did not answer {path}.")  # pragma: no cover

    @staticmethod
    def _rate_limit_wait(response: httpx.Response) -> float | None:
        """Seconds GitHub wants us to wait, or None if this isn't a rate-limit response."""
        if response.status_code not in (403, 429):
            return None
        retry_after = response.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        if response.headers.get("x-ratelimit-remaining") == "0":
            reset = response.headers.get("x-ratelimit-reset")
            if reset and reset.isdigit():
                return max(1.0, float(reset) - time.time())
            return 60.0
        return 60.0 if response.status_code == 429 else None


# --- repository reads -----------------------------------------------------------------------


def _next_page_exists(response: httpx.Response) -> bool:
    return 'rel="next"' in response.headers.get("link", "")


def _last_page(response: httpx.Response) -> int | None:
    match = re.search(r'[?&]page=(\d+)[^>]*>;\s*rel="last"', response.headers.get("link", ""))
    return int(match.group(1)) if match else None


def _json_list(response: httpx.Response, what: str) -> list[dict[str, Any]]:
    data = response.json()
    if not isinstance(data, list):
        raise GithubApiError(f"GitHub's {what} response was not a list.")
    return [item for item in data if isinstance(item, dict)]


async def list_owned_public_repos(http: GithubHttp, login: str) -> list[dict[str, Any]]:
    """The account's own public repositories, most recently pushed first.

    `/users/{login}/repos` is used, not `/user/repos`: for a GitHub App user token with no
    installation, `/user/repos` only returns repositories the app can reach."""
    repos: list[dict[str, Any]] = []
    for page in range(1, MAX_REPO_PAGES + 1):
        response = await http.get(
            f"/users/{login}/repos?type=owner&sort=pushed&per_page=100&page={page}"
        )
        for raw in _json_list(response, "repositories"):
            license_info = raw.get("license") or {}
            repos.append(
                {
                    "id": raw.get("id"),
                    "name": raw.get("name"),
                    "full_name": raw.get("full_name"),
                    "html_url": raw.get("html_url"),
                    "description": raw.get("description"),
                    "fork": bool(raw.get("fork")),
                    "archived": bool(raw.get("archived")),
                    "language": raw.get("language"),
                    "topics": raw.get("topics") or [],
                    "stars": raw.get("stargazers_count") or 0,
                    "forks": raw.get("forks_count") or 0,
                    "license_spdx": license_info.get("spdx_id")
                    if isinstance(license_info, dict)
                    else None,
                    "homepage": raw.get("homepage") or None,
                    "default_branch": raw.get("default_branch"),
                    "created_at": raw.get("created_at"),
                    "pushed_at": raw.get("pushed_at"),
                }
            )
        if not _next_page_exists(response):
            break
    return [r for r in repos if r["id"] and r["name"] and r["full_name"] and r["html_url"]]


async def get_languages(http: GithubHttp, full_name: str) -> dict[str, int]:
    response = await http.get(f"/repos/{full_name}/languages")
    data = response.json()
    if not isinstance(data, dict):
        raise GithubApiError("GitHub's languages response was not an object.")
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int)}


@dataclass(frozen=True)
class CommitStats:
    count: int
    first_at: str | None
    last_at: str | None


def _commit_date(item: dict[str, Any]) -> str | None:
    commit = item.get("commit") or {}
    for who in ("author", "committer"):
        date = (commit.get(who) or {}).get("date")
        if isinstance(date, str):
            return date
    return None


async def get_commit_stats(http: GithubHttp, full_name: str, author: str) -> CommitStats:
    """How many commits GitHub attributes to `author` (a login), and when. Two requests at most:
    one page of size 1 gives the newest commit and, through the `Link` header, the total; the
    last page gives the oldest. An empty repository answers 409 and counts as no commits."""
    path = f"/repos/{full_name}/commits?author={author}&per_page=1"
    response = await http.get(path, allow=(409,))
    if response.status_code == 409:
        return CommitStats(0, None, None)
    items = _json_list(response, "commits")
    if not items:
        return CommitStats(0, None, None)
    last_at = _commit_date(items[0])
    total = _last_page(response) or 1
    first_at = last_at
    if total > 1:
        oldest = _json_list(await http.get(f"{path}&page={total}"), "commits")
        first_at = _commit_date(oldest[0]) if oldest else last_at
    return CommitStats(total, first_at, last_at)


@dataclass(frozen=True)
class TreeEntry:
    path: str
    type: str  # "blob" (a file) or "tree" (a folder)


async def list_tree(http: GithubHttp, full_name: str, ref: str) -> tuple[list[TreeEntry], bool]:
    """Every path in the repository at `ref`, in one request, and whether GitHub cut the list off
    (very large repositories). An empty repository answers 404 or 409 and has no paths."""
    response = await http.get(f"/repos/{full_name}/git/trees/{ref}?recursive=1", allow=(404, 409))
    if response.status_code in (404, 409):
        return [], False
    data = response.json()
    tree = data.get("tree") if isinstance(data, dict) else None
    if not isinstance(tree, list):
        raise GithubApiError("GitHub's tree response had no file list.")
    entries = [
        TreeEntry(str(item["path"]), str(item.get("type", "blob")))
        for item in tree
        if isinstance(item, dict) and item.get("path")
    ]
    return entries, bool(data.get("truncated"))


async def get_text_file(http: GithubHttp, full_name: str, path: str) -> str | None:
    """A small text file's contents, or None if it's missing, too large, or not UTF-8."""
    response = await http.get(f"/repos/{full_name}/contents/{path}", allow=(404,))
    if response.status_code == 404:
        return None
    data = response.json()
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return None
    if int(data.get("size") or 0) > MAX_FILE_BYTES:
        return None
    try:
        return base64.b64decode(data.get("content") or "").decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


async def list_public_events(
    http: GithubHttp, login: str, *, pages: int = 3
) -> list[dict[str, Any]]:
    """Recent public events (GitHub keeps about 90 days, at most 300)."""
    events: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        response = await http.get(f"/users/{login}/events/public?per_page=100&page={page}")
        events.extend(_json_list(response, "events"))
        if not _next_page_exists(response):
            break
    return events
