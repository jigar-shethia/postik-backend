"""
Common API Dependencies & Security Injections
=============================================
This module defines reusable FastAPI dependencies for database sessions, Redis clients,
and authentication token verification.

Beginner Concepts:
------------------
1. **HTTPBearer & Authorization Header**:
   When mobile or web apps call protected endpoints, they pass the JWT in the HTTP header:
       `Authorization: Bearer <your_jwt_token_here>`
   FastAPI's `HTTPBearer` extracts this token automatically.

2. **Scope Enforcement in Dependencies**:
   - `get_current_user`: Ensures the token is signed, unexpired, has `scope="access"`, 
     and that the user exists in PostgreSQL and is active.
   - `get_verified_registration_claims`: Ensures the token has `scope="register"`, 
     and extracts the phone number and unique `jti`.
"""

import datetime
import uuid
from typing import Annotated, Any, Dict
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

# Standard FastAPI Bearer scheme extractor
bearer_scheme = HTTPBearer(auto_error=True)


# ==============================================================================
# 1. Core Infrastructure Dependencies
# ==============================================================================

# Injects an active PostgreSQL AsyncSession with auto-commit/rollback
SessionDep = Annotated[AsyncSession, Depends(get_db)]

# Injects the active Redis client
RedisDep = Annotated[Redis, Depends(get_redis)]


# ==============================================================================
# 2. Authentication & Authorization Dependencies
# ==============================================================================

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: SessionDep,
) -> User:
    """
    FastAPI Dependency that extracts, decodes, and validates an Access JWT token,
    and returns the authenticated User record from the database.
    
    Security Checks:
    1. Valid cryptographic signature and unexpired token.
    2. Enforces `scope == 'access'`.
    3. Verifies user exists in PostgreSQL.
    4. Verifies account is active (`is_active == True`).
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials: Token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce scope isolation
    scope = payload.get("scope")
    if scope != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token scope: Expected 'access' token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: Missing subject identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject: Malformed user UUID.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user from PostgreSQL
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with this token no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


async def get_verified_registration_claims(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> Dict[str, Any]:
    """
    FastAPI Dependency that validates a short-lived Registration JWT token.
    
    Security Checks:
    1. Valid cryptographic signature and unexpired token.
    2. Enforces `scope == 'register'`.
    3. Extracts `sub` (phone), `jti` (unique UUID), and `exp`.
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired registration token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce scope isolation
    scope = payload.get("scope")
    if scope != "register":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token scope: Expected 'register' token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    phone = payload.get("sub")
    jti = payload.get("jti")
    exp = payload.get("exp")

    if not phone or not jti or not exp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed registration token: Missing essential claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    remaining_ttl = max(exp - now, 1)

    return {
        "phone": str(phone),
        "jti": str(jti),
        "exp": exp,
        "remaining_ttl": remaining_ttl,
    }


# Typed aliases for route handlers
CurrentUserDep = Annotated[User, Depends(get_current_user)]
RegistrationClaimsDep = Annotated[Dict[str, Any], Depends(get_verified_registration_claims)]
