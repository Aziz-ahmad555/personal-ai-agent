from httpx import AsyncClient


async def test_health_reports_database_status(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["database"]["status"] == "ok"
    assert body["status"] in {"ok", "error"}
    assert "redis" in body
