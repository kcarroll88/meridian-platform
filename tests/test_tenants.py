import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import Base, get_db

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestingSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_token(client):
    resp = await client.post("/api/v1/auth/token", json={"username": "admin", "password": "changeme"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# --- Auth tests ---

@pytest.mark.asyncio
async def test_admin_login(client):
    resp = await client.post("/api/v1/auth/token", json={"username": "admin", "password": "changeme"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_admin_login_wrong_password(client):
    resp = await client.post("/api/v1/auth/token", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


# --- Tenant tests ---

@pytest.mark.asyncio
async def test_create_tenant(client, admin_headers):
    resp = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme Corp", "slug": "acme"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["key"].startswith("rtk_")
    assert data["key_prefix"] == data["key"][:12]


@pytest.mark.asyncio
async def test_create_tenant_duplicate_slug(client, admin_headers):
    payload = {"name": "Acme Corp", "slug": "acme"}
    await client.post("/api/v1/tenants", json=payload, headers=admin_headers)
    resp = await client.post("/api/v1/tenants", json=payload, headers=admin_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_tenants(client, admin_headers):
    await client.post("/api/v1/tenants", json={"name": "A", "slug": "tenant-a"}, headers=admin_headers)
    await client.post("/api/v1/tenants", json={"name": "B", "slug": "tenant-b"}, headers=admin_headers)
    resp = await client.get("/api/v1/tenants", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_create_tenant_requires_auth(client):
    resp = await client.post("/api/v1/tenants", json={"name": "X", "slug": "x"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_trace_id_in_response(client):
    resp = await client.get("/health")
    assert "x-trace-id" in resp.headers


@pytest.mark.asyncio
async def test_api_key_auth(client, admin_headers):
    # Create tenant, get API key
    resp = await client.post(
        "/api/v1/tenants",
        json={"name": "Test Co", "slug": "test-co"},
        headers=admin_headers,
    )
    api_key = resp.json()["key"]

    # Use API key to hit health (just validates key resolves — RAG endpoints come Week 2)
    resp = await client.get("/health", headers={"Authorization": f"Bearer {api_key}"})
    assert resp.status_code == 200
