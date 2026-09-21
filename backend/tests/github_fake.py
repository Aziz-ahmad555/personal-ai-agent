"""A fake GitHub for tests: canned responses keyed by request path, shaped like the real API and
like the real account this was built against (a Python project, a mixed JS/Python project, and a
notebook-dominated repo whose commits aren't attributed to the owner)."""

import base64
import json
from collections.abc import Callable

import httpx

REAL_CLIENT = httpx.AsyncClient

Route = httpx.Response | Callable[[httpx.Request], httpx.Response]


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def ok(data: object, *, link: str | None = None, status: int = 200) -> httpx.Response:
    headers = {"link": link} if link else {}
    return httpx.Response(status, json=data, headers=headers)


def repo(rid: int, name: str, **overrides: object) -> dict:
    base = {
        "id": rid,
        "name": name,
        "full_name": f"me/{name}",
        "html_url": f"https://github.com/me/{name}",
        "description": f"{name}: a project used in tests",
        "fork": False,
        "archived": False,
        "language": "Python",
        "topics": [],
        "stargazers_count": 0,
        "forks_count": 0,
        "license": None,
        "homepage": None,
        "default_branch": "main",
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-09-12T10:00:00Z",
    }
    base.update(overrides)
    return base


def commit(date: str) -> dict:
    return {"commit": {"author": {"date": date}, "committer": {"date": date}}}


def link(total: int, path: str) -> str:
    return (
        f'<https://api.github.com{path}&page=2>; rel="next", '
        f'<https://api.github.com{path}&page={total}>; rel="last"'
    )


class FakeGitHub:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        target = request.url.raw_path.decode()
        self.requests.append(target)
        route = self.routes.get(target) or self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"message": "not routed in the fake"})
        return route(request) if callable(route) else route

    def client_factory(self) -> Callable[..., httpx.AsyncClient]:
        transport = httpx.MockTransport(self.handler)
        return lambda **kwargs: REAL_CLIENT(transport=transport)

    # --- canned scenarios ---------------------------------------------------------------

    def user(self, login: str = "me", **profile: object) -> None:
        self.routes["/user"] = ok({"login": login, "id": 1, **profile})

    def repos(self, *repos: dict, login: str = "me") -> None:
        path = f"/users/{login}/repos"
        self.routes[f"{path}?type=owner&sort=pushed&per_page=100&page=1"] = ok(list(repos))

    def project(
        self,
        name: str,
        *,
        languages: dict[str, int],
        commits: int,
        files: dict[str, str] | None = None,
        newest: str = "2026-09-12T10:00:00Z",
        oldest: str = "2026-03-01T10:00:00Z",
        readme: str | None = "# Project\n\nA short README.\n",
    ) -> None:
        """Everything a detail pass reads for one repo."""
        base = f"/repos/me/{name}"
        self.routes[f"{base}/languages"] = ok(languages)
        commits_path = f"{base}/commits?author=me&per_page=1"
        if commits == 0:
            self.routes[commits_path] = ok([])
        elif commits == 1:
            self.routes[commits_path] = ok([commit(newest)])
        else:
            self.routes[commits_path] = ok(
                [commit(newest)],
                link=link(commits, f"/repos/me/{name}/commits?author=me&per_page=1"),
            )
            self.routes[f"{commits_path}&page={commits}"] = ok([commit(oldest)])
        files = files or {}
        tree = [{"path": "README.md", "type": "blob"}] if readme is not None else []
        if readme is not None:
            self.routes[f"{base}/contents/README.md"] = ok(
                {"encoding": "base64", "content": b64(readme), "size": len(readme)}
            )
        for path in files:
            folder = path.rsplit("/", 1)[0] if "/" in path else None
            if folder and {"path": folder, "type": "tree"} not in tree:
                tree.append({"path": folder, "type": "tree"})
            tree.append({"path": path, "type": "blob"})
        self.routes[f"{base}/git/trees/main?recursive=1"] = ok({"tree": tree, "truncated": False})
        for path, text in files.items():
            self.routes[f"{base}/contents/{path}"] = ok(
                {"encoding": "base64", "content": b64(text), "size": len(text)}
            )

    def events(self, *dates: str) -> None:
        self.routes["/users/me/events/public?per_page=100&page=1"] = ok(
            [{"type": "PushEvent", "created_at": d} for d in dates]
        )

    def account(self) -> None:
        """The standard account: two real projects, a notebook repo, a fork and an archive. Like
        the real one, AegisAI has no README and smart-campus-ai has a partial download committed."""
        self.user(
            name="Aziz Ahmad",
            bio="ML engineer building vision systems",
            location="Lahore",
            blog="",
            public_repos=3,
        )
        self.repos(
            repo(1, "AegisAI"),
            repo(2, "smart-campus-ai", language="JavaScript", pushed_at="2026-08-31T10:00:00Z"),
            repo(3, "plant-disease-classifier", language="Jupyter Notebook"),
            repo(4, "someone-elses-project", fork=True),
            repo(5, "old-experiment", archived=True),
        )
        self.project(
            "AegisAI",
            languages={"Python": 114_846, "HTML": 62_339},
            commits=43,
            files={
                "requirements.txt": "fastapi>=0.110\nsqlalchemy\nuvicorn\n",
                "Dockerfile": "FROM python:3.12\n",
            },
            readme=None,
        )
        self.project(
            "smart-campus-ai",
            languages={"JavaScript": 78_123, "Python": 53_752, "CSS": 2_917, "HTML": 360},
            commits=29,
            newest="2026-08-31T10:00:00Z",
            files={
                "frontend/package.json": json.dumps({"dependencies": {"react": "^19"}}),
                "backend/requirements.txt": "fastapi\nnumpy\n",
                ".yolov8n-pose.pt.38fb.part": "",
            },
        )
        self.project(
            "plant-disease-classifier",
            languages={"Jupyter Notebook": 536_469, "Python": 1_384},
            commits=0,
        )
        self.events("2026-09-10T08:00:00Z", "2026-09-12T08:00:00Z")
