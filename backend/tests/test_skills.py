from httpx import AsyncClient


async def test_create_skill_and_reject_duplicate_name(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.post("/profile/skills", headers=auth_headers, json={"name": "Python"})
    assert first.status_code == 201
    assert first.json()["versions"] == []

    duplicate = await client.post("/profile/skills", headers=auth_headers, json={"name": "Python"})
    assert duplicate.status_code == 409


async def test_add_skill_version_requires_real_evidence(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    skill = await client.post("/profile/skills", headers=auth_headers, json={"name": "PyTorch"})
    skill_id = skill.json()["id"]

    too_short = await client.post(
        f"/profile/skills/{skill_id}/versions",
        headers=auth_headers,
        json={"level": "advanced", "evidence": "used it"},
    )
    assert too_short.status_code == 422


async def test_add_skill_version_and_read_history(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    skill = await client.post("/profile/skills", headers=auth_headers, json={"name": "Rust"})
    skill_id = skill.json()["id"]

    v1 = await client.post(
        f"/profile/skills/{skill_id}/versions",
        headers=auth_headers,
        json={"level": "beginner", "evidence": "Completed the official Rust book exercises."},
    )
    assert v1.status_code == 201

    v2 = await client.post(
        f"/profile/skills/{skill_id}/versions",
        headers=auth_headers,
        json={"level": "intermediate", "evidence": "Shipped a CLI tool used by the team daily."},
    )
    assert v2.status_code == 201

    history = await client.get(f"/profile/skills/{skill_id}/versions", headers=auth_headers)
    assert history.status_code == 200
    levels = [v["level"] for v in history.json()]
    # Newest first — history is append-only, never overwritten.
    assert levels == ["intermediate", "beginner"]


async def test_skill_version_can_reference_work_experience(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    experience = await client.post(
        "/profile/experience",
        headers=auth_headers,
        json={"company": "Acme", "title": "Engineer", "start_date": "2022-01-01"},
    )
    experience_id = experience.json()["id"]

    skill = await client.post("/profile/skills", headers=auth_headers, json={"name": "SQL"})
    skill_id = skill.json()["id"]

    version = await client.post(
        f"/profile/skills/{skill_id}/versions",
        headers=auth_headers,
        json={
            "level": "expert",
            "evidence": "Owned the data warehouse migration end to end.",
            "work_experience_id": experience_id,
        },
    )
    assert version.status_code == 201
    assert version.json()["work_experience_id"] == experience_id


async def test_skill_version_rejects_unowned_work_experience(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    skill = await client.post("/profile/skills", headers=auth_headers, json={"name": "Go"})
    skill_id = skill.json()["id"]

    version = await client.post(
        f"/profile/skills/{skill_id}/versions",
        headers=auth_headers,
        json={
            "level": "beginner",
            "evidence": "Wrote a small internal tool.",
            "work_experience_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert version.status_code == 404


async def test_delete_skill_cascades_versions(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    skill = await client.post("/profile/skills", headers=auth_headers, json={"name": "Kotlin"})
    skill_id = skill.json()["id"]
    await client.post(
        f"/profile/skills/{skill_id}/versions",
        headers=auth_headers,
        json={"level": "beginner", "evidence": "Built a small Android side project."},
    )

    delete = await client.delete(f"/profile/skills/{skill_id}", headers=auth_headers)
    assert delete.status_code == 204

    listing = await client.get("/profile/skills", headers=auth_headers)
    assert listing.json() == []
