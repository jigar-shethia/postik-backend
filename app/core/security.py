"""
Security Core: JWT Tokens, Hashing & Replay Protection
======================================================
This module provides cryptographic utilities for generating and validating scoped 
JSON Web Tokens (JWTs), creating random refresh tokens, and preventing token replay attacks.

Beginner Concepts:
------------------
1. **What is a JWT (JSON Web Token)?**:
   A JWT is a digitally signed, URL-safe JSON string composed of three base64 parts separated by dots:
       `[Header].[Payload].[Signature]`
   - **Header**: Specifies the hashing algorithm (e.g. HS256).
   - **Payload (Claims)**: Contains data like user ID (`sub`), permissions (`scope`), and expiration (`exp`).
   - **Signature**: Formed by hashing `Header + Payload` with our secret key (`JWT_SECRET_KEY`).
   
   Because only our backend knows the `JWT_SECRET_KEY`, if a user tries to edit the user ID in the token, 
   the cryptographic signature will not match and FastAPI will reject the request immediately!

2. **Scope Isolation (`scope="access"` vs `scope="register"`)**:
   - **Access Token (`scope="access"`)**: Full API access for logged-in users.
   - **Registration Token (`scope="register"`)**: Limited-use token issued after OTP verification to new users.
   
   *Security Guarantee*: A registration token CANNOT be used to call private user endpoints (like `/auth/me`), 
   and an access token cannot be used to register a new user.

3. **JTI & Token Replay Attack Protection**:
   `jti` stands for "JWT ID" (a unique UUID per token).
   When a new user submits their registration token, Redis executes:
       `SET consumed:jti:<jti> 1 NX EX <remaining_seconds>`
   `NX` means "Set ONLY if Not Exists". If an attacker intercepts the registration token and tries 
   to submit it again, Redis returns False and the request is blocked!
"""

import datetime
import hashlib
import logging
import secrets
import uuid
from typing import Any, Dict, Optional, Tuple

import jwt
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger("security")


# ==============================================================================
# 1. Hashing Helpers
# ==============================================================================

def hash_token(raw_token: str) -> str:
    """
    Computes a SHA-256 hash of a raw token string.
    Used for storing refresh tokens in the database without saving raw secrets.
    """
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


# ==============================================================================
# 2. Token Generation
# ==============================================================================

def create_access_token(user_id: str) -> str:
    """
    Generates a short-lived Access JWT for an authenticated user.
    
    Claims:
    -------
    - `sub`   : User's UUID string.
    - `scope` : "access" (identifies this as a full access token).
    - `exp`   : Expiration timestamp (now + ACCESS_TOKEN_EXPIRE_MINUTES, default 60m).
    - `iat`   : Issued-at timestamp.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    expire = now + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "scope": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token() -> Tuple[str, str]:
    """
    Generates a cryptographically strong random Refresh Token and its SHA-256 hash.
    
    Returns:
    --------
    (raw_token, token_hash)
    - `raw_token`  : Sent to the client app (held securely in device keychain/keystore).
    - `token_hash` : Stored in PostgreSQL `refresh_sessions` table.
    """
    # 32 bytes of secure entropy encoded in URL-safe base64 (approx 43 characters)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    return raw_token, token_hash


def create_registration_token(phone: str) -> str:
    """
    Generates a short-lived temporary Registration JWT for a newly verified phone number.
    
    Claims:
    -------
    - `sub`   : Verified phone number (e.g. "+1234567890").
    - `scope` : "register" (restricts this token ONLY to the /auth/register endpoint).
    - `jti`   : Unique UUID preventing replay/reuse of this registration token.
    - `exp`   : Expiration timestamp (now + REGISTRATION_TOKEN_EXPIRE_MINUTES, default 10m).
    - `iat`   : Issued-at timestamp.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    expire = now + datetime.timedelta(minutes=settings.REGISTRATION_TOKEN_EXPIRE_MINUTES)
    
    payload: Dict[str, Any] = {
        "sub": phone,
        "scope": "register",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ==============================================================================
# 3. Token Decoding & Validation
# ==============================================================================

def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodes and cryptographically verifies a JWT token.
    
    Returns:
    --------
    dict of payload claims if signature and expiration are valid, None otherwise.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "scope"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token verification failed: Signature has expired.")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning(f"Token verification failed: Invalid token ({exc}).")
        return None


# ==============================================================================
# 4. Redis Replay Guard (One-Time Token Consumption)
# ==============================================================================

async def mark_jti_consumed(redis: Redis, jti: str, ttl_seconds: int) -> bool:
    """
    Atomically marks a registration token JTI as consumed in Redis using 'SET NX'.
    
    Parameters:
    -----------
    redis       : Async Redis client.
    jti         : The unique JWT ID string from the registration token.
    ttl_seconds : How long to remember the consumed JTI (remaining token lifetime).
    
    Returns:
    --------
    bool : True if the token was fresh and marked consumed successfully.
           False if the token was ALREADY consumed (Replay attack detected!).
    """
    key = f"consumed:jti:{jti}"
    # 'nx=True' guarantees that if the key already exists, Redis does NOT overwrite it and returns None
    result = await redis.set(key, "1", ex=max(ttl_seconds, 1), nx=True)
    return bool(result)
