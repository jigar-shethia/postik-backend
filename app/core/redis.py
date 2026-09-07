"""
Redis Connection & Lifecycle Management
=======================================
This module sets up an asynchronous connection pool to Redis using `redis.asyncio`.

Beginner Concepts:
------------------
1. **What is Redis?**:
   Redis is an ultra-fast, in-memory key-value database.
   Unlike PostgreSQL (which writes to disk and handles complex relational tables),
   Redis keeps data in RAM. It is ideal for temporary data that needs fast access:
   - OTP codes (stored for 5 minutes)
   - Rate limit counters (tracking requests per second/minute)
   - One-time registration tokens (preventing token reuse)

2. **Connection Pooling**:
   Creating a brand-new network connection to Redis for every single HTTP request is slow.
   A "Connection Pool" maintains a fixed set of open connections (e.g. 20) and reuses them,
   greatly improving performance and reducing server overhead.

3. **Singleton Pattern**:
   We initialize `redis_client` once and share that single client instance across the application.
"""

import logging
from typing import AsyncGenerator, Optional
import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global singleton reference to the Redis client
redis_client: Optional[Redis] = None


def get_redis_client() -> Redis:
    """
    Returns the singleton Redis client instance.
    If it has not been created yet, it initializes the connection pool.
    
    `decode_responses=True` ensures Redis automatically decodes byte responses into Python strings.
    """
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return redis_client


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    FastAPI Dependency:
    Injects the active Redis client into route functions that need it.
    
    Example Usage in an endpoint:
    -----------------------------
    @router.get("/example")
    async def example_endpoint(redis: Redis = Depends(get_redis)):
        await redis.set("my_key", "my_value", ex=60)
    """
    client = get_redis_client()
    yield client


async def check_redis_health() -> bool:
    """
    Health Check Helper:
    Sends a 'PING' command to Redis and expects a 'PONG' response.
    Returns True if Redis is reachable and responding, False otherwise.
    """
    try:
        client = get_redis_client()
        pong = await client.ping()
        return bool(pong)
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return False


async def close_redis_connection() -> None:
    """
    Graceful Shutdown:
    Closes all open sockets in the Redis connection pool when the application stops.
    This prevents dangling network connections on the server.
    """
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis connection pool closed.")
