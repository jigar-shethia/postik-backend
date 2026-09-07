"""
Common API Dependencies & Type Aliases
======================================
This module defines reusable dependencies that can be injected into any FastAPI endpoint.

Beginner Concepts:
------------------
1. **Dependency Injection (DI)**:
   Instead of manually creating database connections, Redis clients, or decoding auth tokens
   inside every single API route function, FastAPI allows you to define reusable functions (dependencies)
   and inject them automatically into endpoint parameters using `Depends(...)`.

2. **`Annotated` (Python 3.9+ / PEP 593)**:
   Allows combining a Python type hint with metadata.
   For example:
       `SessionDep = Annotated[AsyncSession, Depends(get_db)]`
   Means: "In any endpoint where you declare `db: SessionDep`, FastAPI knows that `db` has the type 
   `AsyncSession`, and FastAPI will automatically call `get_db()` and pass the result."

Example Usage in a Route:
-------------------------
```python
from app.api.deps import SessionDep, RedisDep

@router.get("/users/count")
async def get_user_count(db: SessionDep, redis: RedisDep):
    # db is an active AsyncSession ready for queries
    # redis is an active Redis client ready for commands
    ...
```
"""

from typing import Annotated
from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.db.session import get_db

# ------------------------------------------------------------------------------
# Dependency Type Aliases
# ------------------------------------------------------------------------------

# Injects an active PostgreSQL AsyncSession into route handlers
SessionDep = Annotated[AsyncSession, Depends(get_db)]

# Injects the active Redis client into route handlers
RedisDep = Annotated[Redis, Depends(get_redis)]
