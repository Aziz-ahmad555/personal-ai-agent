from httpx import AsyncClient


async def test_get_preferences_returns_sane_defaults(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/profile/preferences", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["job_types"] == []
    assert body["remote_preference"] == "no_preference"


async def test_update_preferences_partial(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/profile/preferences",
        headers=auth_headers,
        json={
            "job_types": ["full_time", "contract"],
            "remote_preference": "remote",
            "salary_min": 90000,
            "salary_max": 130000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_types"] == ["full_time", "contract"]
    assert body["remote_preference"] == "remote"
    assert body["salary_min"] == 90000
    assert body["salary_max"] == 130000
    assert body["locations"] == []  # untouched by this partial update


async def test_salary_min_greater_than_max_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/profile/preferences",
        headers=auth_headers,
        json={"salary_min": 200000, "salary_max": 100000},
    )
    assert response.status_code == 422
