"""
Database Session & Connection Engine
====================================
This module configures the asynchronous PostgreSQL engine and manages database sessions.

Beginner Concepts:
------------------
1. **Asynchronous I/O (`async` / `await`)**:
   In traditional synchronous backends, when a request waits for PostgreSQL to finish a query (e.g. 20ms),
   the entire server thread is blocked from doing anything else.
   With `asyncpg` and async SQLAlchemy, while waiting for the database response, FastAPI pauses 
   that specific coroutine and handles hundreds of other incoming user requests in parallel.

2. **Engine vs. Session**:
   - **Engine**: The core connection pool and dialer that speaks directly to PostgreSQL over TCP.
   - **Session**: A "workspace" or transaction representing a single unit of work (e.g. one HTTP request).
     You use a session to query, add, update, or delete records, and then either commit or roll back.

3. **Dependency Injection & Automatic Rollback**:
   The `get_db()` generator is used as a FastAPI dependency. It opens a clean database session for 
   the route, yields it to your endpoint, automatically commits changes if the route succeeds,
   or rolls back everything if an exception occurs — preventing database corruption.
"""

import logging
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Async Database Engine
# ------------------------------------------------------------------------------
# The engine manages the pool of connections to PostgreSQL.
engine = create_async_engine(
    settings.ASYNC_DATABASE_URI,
    echo=settings.DEBUG,     # If True, prints raw SQL queries in terminal (great for learning & debugging)
    future=True,             # Uses SQLAlchemy 2.0 modern API
    pool_pre_ping=True,      # Tests connection before using it (avoids stale/dropped connections)
    pool_size=10,            # Keeps 10 persistent open connections in reserve
    max_overflow=20,         # Can temporarily open 20 extra connections during traffic spikes
)

# ------------------------------------------------------------------------------
# 2. Async Session Factory
# ------------------------------------------------------------------------------
# A factory for generating new AsyncSession objects with predefined settings.
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Prevents attributes from expiring after commit (safe for async use)
    autocommit=False,        # Explicit transaction control
    autoflush=False,
)


# ------------------------------------------------------------------------------
# 3. FastAPI Dependency: get_db()
# ------------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Dependency that yields an AsyncSession for the lifecycle of an HTTP request.
    
    Data Flow:
    1. HTTP Request comes in -> get_db() opens a session from the connection pool.
    2. Endpoint function executes business logic and database queries.
    3. If no errors occur -> session.commit() saves all changes to PostgreSQL.
    4. If ANY error occurs -> session.rollback() undos any partial changes.
    5. finally block -> session.close() returns the connection back to the pool.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database transaction rolled back due to error: {e}")
            raise
        finally:
            await session.close()


# Alias for backward compatibility
get_async_db = get_db


# ------------------------------------------------------------------------------
# 4. Database Health Check Utility
# ------------------------------------------------------------------------------
async def check_db_health() -> bool:
    """
    Executes a simple 'SELECT 1;' query on PostgreSQL to confirm the database 
    is alive, reachable, and ready to accept queries.
    """
    try:
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False


# ------------------------------------------------------------------------------
# 5. Engine Shutdown
# ------------------------------------------------------------------------------
async def close_db_connection() -> None:
    """
    Closes all database connections in the engine pool gracefully upon server shutdown.
    """
    await engine.dispose()
    logger.info("Database connection engine disposed.")
