from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        SHARED_PASSWORD="test-password",
        JWT_SECRET_KEY="test-secret-key",
        RESULTS_PER_IMAGE=3,
        CAROUSEL_SIZE=2,
        FRACTURE_EDITOR_ENABLED=True,
        STORAGE_PROVIDER="local",
        LOCAL_STORAGE_ROOT=tmp_path / "storage",
        CORS_ORIGINS=["http://localhost:3000"],
    )


@pytest.fixture
def app(settings: Settings):
    app = create_app(settings)
    return app


@pytest.fixture
async def client(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as async_client:
        yield async_client


@pytest.fixture
def settings_fracture_disabled(tmp_path: Path) -> Settings:
    return Settings(
        SHARED_PASSWORD="test-password",
        JWT_SECRET_KEY="test-secret-key",
        RESULTS_PER_IMAGE=3,
        CAROUSEL_SIZE=2,
        FRACTURE_EDITOR_ENABLED=False,
        STORAGE_PROVIDER="local",
        LOCAL_STORAGE_ROOT=tmp_path / "storage",
        CORS_ORIGINS=["http://localhost:3000"],
    )


@pytest.fixture
async def client_fracture_disabled(settings_fracture_disabled: Settings) -> AsyncClient:
    app = create_app(settings_fracture_disabled)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as async_client:
        yield async_client


@pytest.fixture
def png_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), color=(120, 40, 220))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/auth/token", data={"password": "test-password"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auth_headers_fracture_disabled(
    client_fracture_disabled: AsyncClient,
) -> dict[str, str]:
    response = await client_fracture_disabled.post(
        "/api/auth/token", data={"password": "test-password"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
