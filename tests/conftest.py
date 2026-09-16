"""
Pytest Test Configuration & Shared Fixtures
===========================================
This module configures the automated testing harness using an in-memory database,
mock async Redis client, and FastAPI test client.

Beginner Concepts:
------------------
1. **Test Isolation (Zero Side Effects)**:
   Tests should never pollute or depend on your real production or development database.
   Every test runs against a fresh in-memory database and a clean Redis cache so tests 
   can run in any order without interfering with each other.

2. **FastAPI `dependency_overrides`**:
   FastAPI allows you to override dependencies (like `get_db` and `get_redis`) during tests.
   When the API handles a request inside a test, it automatically uses the test database 
   and test Redis rather than connecting to live servers.

3. **`httpx.AsyncClient` with `ASGITransport`**:
   Directly executes HTTP requests against your FastAPI app in-memory without needing 
   to start a real Uvicorn server on a network port.
"""

import asyncio
from typing import AsyncGenerator
import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db, get_redis
from app.db.base import Base
from app.main import app

# ------------------------------------------------------------------------------
# 1. In-Memory SQLite Async Database for Testing
# ------------------------------------------------------------------------------
# Uses SQLite with StaticPool so all connections share the exact same in-memory DB
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Creates fresh database tables for each test and drops them afterward.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def test_redis() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    """
    Provides a clean in-memory fake Redis instance for each test.
    """
    fake_r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await fake_r.flushall()
    yield fake_r
    await fake_r.aclose()


@pytest_asyncio.fixture(scope="function")
async def client(
    test_db: AsyncSession, test_redis: fakeredis.aioredis.FakeRedis
) -> AsyncGenerator[AsyncClient, None]:
    """
    Creates an asynchronous HTTP test client with FastAPI dependency overrides.
    """
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield test_db
            await test_db.commit()
        except Exception:
            await test_db.rollback()
            raise

    async def override_get_redis() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
        yield test_redis

    # Apply FastAPI dependency overrides
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up overrides after test completes
    app.dependency_overrides.clear()
