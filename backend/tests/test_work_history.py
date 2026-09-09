from httpx import AsyncClient

EXPERIENCE_PAYLOAD = {
    "company": "Acme Corp",
    "title": "Senior Engineer",
    "location": "Remote",
    "start_date": "2022-01-01",
    "end_date": None,
    "description": "Led the platform team.",
}


async def test_create_list_update_delete_experience(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    create = await client.post("/profile/experience", headers=auth_headers, json=EXPERIENCE_PAYLOAD)
    assert create.status_code == 201
    experience_id = create.json()["id"]

    listing = await client.get("/profile/experience", headers=auth_headers)
    assert len(listing.json()) == 1

    update = await client.put(
        f"/profile/experience/{experience_id}",
        headers=auth_headers,
        json={"title": "Staff Engineer"},
    )
    assert update.status_code == 200
    assert update.json()["title"] == "Staff Engineer"
    assert update.json()["company"] == "Acme Corp"  # untouched fields survive a partial update

    delete = await client.delete(f"/profile/experience/{experience_id}", headers=auth_headers)
    assert delete.status_code == 204

    listing_after = await client.get("/profile/experience", headers=auth_headers)
    assert listing_after.json() == []


async def test_experience_end_date_before_start_date_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {**EXPERIENCE_PAYLOAD, "start_date": "2022-01-01", "end_date": "2021-01-01"}
    response = await client.post("/profile/experience", headers=auth_headers, json=payload)
    assert response.status_code == 422


async def test_experience_not_found_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/profile/experience/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
        json={"title": "Anything"},
    )
    assert response.status_code == 404


async def test_create_list_update_delete_education(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "institution": "State University",
        "degree": "BSc",
        "field": "Computer Science",
        "start_date": "2018-09-01",
        "end_date": "2022-06-01",
    }
    create = await client.post("/profile/education", headers=auth_headers, json=payload)
    assert create.status_code == 201
    education_id = create.json()["id"]

    update = await client.put(
        f"/profile/education/{education_id}", headers=auth_headers, json={"degree": "MSc"}
    )
    assert update.status_code == 200
    assert update.json()["degree"] == "MSc"

    delete = await client.delete(f"/profile/education/{education_id}", headers=auth_headers)
    assert delete.status_code == 204

    listing = await client.get("/profile/education", headers=auth_headers)
    assert listing.json() == []
