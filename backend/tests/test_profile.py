from httpx import AsyncClient


async def test_profile_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/profile")
    assert response.status_code == 401


async def test_get_profile_auto_creates_empty_profile(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/profile", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["headline"] is None
    assert body["links"] == []


async def test_update_profile_sets_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/profile",
        headers=auth_headers,
        json={"headline": "ML Engineer", "summary": "Builds things.", "location": "Remote"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "ML Engineer"
    assert body["summary"] == "Builds things."
    assert body["location"] == "Remote"


async def test_add_and_delete_link(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    add = await client.post(
        "/profile/links",
        headers=auth_headers,
        json={"label": "GitHub", "url": "https://github.com/example"},
    )
    assert add.status_code == 201
    link_id = add.json()["id"]

    profile = await client.get("/profile", headers=auth_headers)
    assert len(profile.json()["links"]) == 1

    delete = await client.delete(f"/profile/links/{link_id}", headers=auth_headers)
    assert delete.status_code == 204

    profile_after = await client.get("/profile", headers=auth_headers)
    assert profile_after.json()["links"] == []


async def test_deleting_nonexistent_link_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    add = await client.post(
        "/profile/links",
        headers=auth_headers,
        json={"label": "GitHub", "url": "https://github.com/example"},
    )
    link_id = add.json()["id"]

    missing = await client.delete(
        "/profile/links/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert missing.status_code == 404

    still_there = await client.get("/profile", headers=auth_headers)
    assert len(still_there.json()["links"]) == 1
    assert still_there.json()["links"][0]["id"] == link_id
