import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_auth_success(client: AsyncClient) -> None:
    response = await client.post("/api/auth/token", data={"password": "test-password"})
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str)
    assert data["expires_in"] > 0


@pytest.mark.anyio
async def test_auth_failure(client: AsyncClient) -> None:
    response = await client.post("/api/auth/token", data={"password": "wrong"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_verify_token(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/auth/verify", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"valid": True}
