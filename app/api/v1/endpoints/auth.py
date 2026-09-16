"""
Authentication API Endpoints
============================
This module implements the complete suite of phone-first authentication routes:
- `POST /api/v1/auth/otp/send`: Request a one-time verification SMS code.
- `POST /api/v1/auth/otp/verify`: Verify submitted OTP and issue tokens / registration flow.
- `POST /api/v1/auth/register`: Onboard new customer by validating registration token and creating user profile.
- `POST /api/v1/auth/refresh`: Rotate refresh tokens with automatic token reuse / theft detection.
- `GET /api/v1/auth/me`: Retrieve the authenticated user's profile.

Beginner Concepts:
------------------
1. **Branching Auth Flow (New vs. Existing User)**:
   In a phone-first architecture, the user doesn't choose between "Login" and "Sign Up" buttons upfront.
   They simply enter their phone number.
   - If the phone exists in the `users` table -> Log in directly by issuing an Access + Refresh token pair.
   - If the phone is new -> Issue a scoped `registration_token` granting permission to complete profile registration.

2. **One-Time Token Enforcement (JTI Replay Guard)**:
   When registering, the client passes `Authorization: Bearer <registration_token>`.
   We atomically mark the token's unique `jti` as consumed in Redis (`SET NX`).
   If the token is re-submitted, Redis rejects it, preventing duplicate signups or replay attacks.

3. **Token Rotation & Theft Detection**:
   Every time a refresh token is used, it is revoked and replaced with a new one (`replaced_by`).
   If an old, already-revoked refresh token is ever submitted, the server detects token theft
   and immediately revokes ALL active sessions for that user.
"""

import datetime
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.api.deps import CurrentUserDep, RedisDep, RegistrationClaimsDep, SessionDep
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_registration_token,
    hash_token,
    mark_jti_consumed,
)
from app.models.session import RefreshSession
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    RegisterRequest,
    SendOTPRequest,
    SendOTPResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserResponse,
    VerifyOTPRequest,
    VerifyOTPResponse,
)
from app.services.otp_service import verify_otp_hash
from app.services.sms.dispatcher import send_and_store_otp

logger = logging.getLogger("api.auth")

router = APIRouter()


def get_client_ip(request: Request) -> str:
    """
    Extracts the client's real IP address from HTTP request headers.
    Supports proxy forwarding headers (X-Forwarded-For).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # The first entry in X-Forwarded-For is the original client IP
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


# ==============================================================================
# 1. POST /api/v1/auth/otp/send
# ==============================================================================

@router.post(
    "/otp/send",
    response_model=SendOTPResponse,
    status_code=status.HTTP_200_OK,
    summary="Send OTP Verification Code",
    description="Dispatches a 6-digit OTP code to the specified phone number via SMS subject to rate limits and cooldowns.",
    responses={
        200: {
            "description": "OTP sent successfully.",
            "model": SendOTPResponse,
        },
        429: {
            "description": "Rate limit or 60-second cooldown active. Check Retry-After header.",
        },
        502: {
            "description": "SMS gateway failure.",
        },
    },
)
async def send_otp(
    payload: SendOTPRequest,
    request: Request,
    redis: RedisDep,
) -> SendOTPResponse:
    """
    Endpoint handler for POST /api/v1/auth/otp/send.
    
    Workflow:
    1. Extract client IP address.
    2. Check multi-tier rate limits (60s cooldown, max 3 per phone, max 20 per IP).
    3. Generate 6-digit OTP and send via SMS Provider.
    4. Persist SHA-256 hash in Redis only upon successful SMS delivery.
    """
    client_ip = get_client_ip(request)
    
    success, reason, retry_in_seconds = await send_and_store_otp(
        redis=redis,
        phone=payload.phone,
        ip=client_ip,
    )

    if not success:
        if reason in [
            "COOLDOWN_ACTIVE",
            "PHONE_RATE_LIMIT_EXCEEDED",
            "IP_RATE_LIMIT_EXCEEDED",
        ]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": reason,
                    "message": "Too many OTP requests. Please wait before requesting another code.",
                    "retry_in_seconds": retry_in_seconds,
                },
                headers={"Retry-After": str(retry_in_seconds)},
            )
        
        # SMS Gateway failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "SMS_DISPATCH_FAILED",
                "message": "Unable to deliver SMS verification code. Please try again later.",
            },
        )

    return SendOTPResponse(
        message="OTP sent successfully",
        retry_in_seconds=retry_in_seconds,
    )


# ==============================================================================
# 2. POST /api/v1/auth/otp/verify
# ==============================================================================

@router.post(
    "/otp/verify",
    response_model=VerifyOTPResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify OTP Code",
    description="Validates the submitted OTP against Redis. If existing user, logs in with JWT tokens; if new user, issues registration token.",
    responses={
        200: {
            "description": "OTP verified successfully.",
            "model": VerifyOTPResponse,
        },
        400: {
            "description": "Invalid, expired, or max attempts exceeded for OTP.",
        },
        403: {
            "description": "Account is deactivated.",
        },
    },
)
async def verify_otp(
    payload: VerifyOTPRequest,
    db: SessionDep,
    redis: RedisDep,
    x_device_id: Optional[str] = Header(
        default=None,
        description="Optional client device identifier (e.g. mobile device model)",
    ),
) -> VerifyOTPResponse:
    """
    Endpoint handler for POST /api/v1/auth/otp/verify.
    
    Workflow:
    1. Verify submitted OTP against Redis SHA-256 hash (constant time).
    2. Check if user already exists in PostgreSQL:
       - YES (Existing User) -> Issue Access + Refresh tokens & record session.
       - NO  (New User)      -> Issue short-lived Registration token.
    """
    # 1. Verify OTP in Redis
    is_valid, verify_status = await verify_otp_hash(
        redis=redis,
        phone=payload.phone,
        submitted_otp=payload.otp,
    )

    if not is_valid:
        error_messages = {
            "EXPIRED_OR_NOT_FOUND": "OTP has expired or was not requested. Please request a new code.",
            "MAX_ATTEMPTS_EXCEEDED": "Too many failed attempts. For your security, this code has been invalidated.",
            "INVALID_OTP": "Incorrect verification code. Please try again.",
        }
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": verify_status,
                "message": error_messages.get(verify_status, "OTP verification failed."),
            },
        )

    # 2. Query PostgreSQL to check if phone is registered
    result = await db.execute(select(User).where(User.phone == payload.phone))
    user = result.scalar_one_or_none()

    # --------------------------------------------------------------------------
    # Branch A: Existing Registered User (Direct Login)
    # --------------------------------------------------------------------------
    if user:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCOUNT_DEACTIVATED",
                    "message": "Your account has been deactivated. Please contact support.",
                },
            )

        # Issue Access and Refresh tokens
        access_token = create_access_token(user_id=str(user.id))
        raw_refresh_token, refresh_token_hash = create_refresh_token()

        # Calculate session expiration
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Record active refresh session in database
        refresh_session = RefreshSession(
            user_id=user.id,
            token_hash=refresh_token_hash,
            device_id=x_device_id,
            expires_at=expires_at,
        )
        db.add(refresh_session)
        # Note: SessionDep automatically commits on response return

        logger.info(f"Existing user {user.id} logged in successfully via OTP.")

        return VerifyOTPResponse(
            is_new_user=False,
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
        )

    # --------------------------------------------------------------------------
    # Branch B: New User (Issue Registration Token)
    # --------------------------------------------------------------------------
    registration_token = create_registration_token(phone=payload.phone)
    logger.info(f"New user with phone {payload.phone} verified OTP. Registration token issued.")

    return VerifyOTPResponse(
        is_new_user=True,
        registration_token=registration_token,
    )


# ==============================================================================
# 3. POST /api/v1/auth/register
# ==============================================================================

@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register New Customer Profile",
    description="Onboards a new customer using a verified registration token from OTP verification.",
    responses={
        201: {
            "description": "User successfully registered.",
            "model": AuthResponse,
        },
        401: {
            "description": "Invalid, expired, or already consumed registration token.",
        },
        409: {
            "description": "Phone number or email is already registered.",
        },
    },
)
async def register_user(
    payload: RegisterRequest,
    claims: RegistrationClaimsDep,
    db: SessionDep,
    redis: RedisDep,
    x_device_id: Optional[str] = Header(
        default=None,
        description="Optional client device identifier (e.g. mobile device model)",
    ),
) -> AuthResponse:
    """
    Endpoint handler for POST /api/v1/auth/register.
    
    Security Workflow:
    1. Validate Bearer token signature and scope == 'register'.
    2. Atomically mark JTI as consumed in Redis using SET NX (blocks token replay).
    3. Defensively check phone uniqueness in PostgreSQL.
    4. Validate email uniqueness if email provided.
    5. Insert customer record in 'users' and initial session in 'refresh_sessions'.
    6. Return access_token, refresh_token, and user profile.
    """
    phone = claims["phone"]
    jti = claims["jti"]
    remaining_ttl = claims["remaining_ttl"]

    # 1. Atomic JTI consumption check in Redis (blocks reuse of this registration token)
    consumed = await mark_jti_consumed(redis, jti, remaining_ttl)
    if not consumed:
        logger.warning(f"Registration replay attempt detected for JTI {jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_ALREADY_CONSUMED",
                "message": "This registration token has already been used. Please verify your phone again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Defensive check: Verify phone is not already taken
    phone_query = await db.execute(select(User).where(User.phone == phone))
    if phone_query.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PHONE_ALREADY_EXISTS",
                "message": "An account with this phone number already exists. Please log in directly.",
            },
        )

    # 3. Check email uniqueness if email is provided
    if payload.email:
        email_query = await db.execute(select(User).where(User.email == payload.email))
        if email_query.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "EMAIL_ALREADY_EXISTS",
                    "message": "This email address is already associated with another account.",
                },
            )

    # 4. Insert new User into PostgreSQL
    new_user = User(
        id=uuid.uuid4(),
        phone=phone,
        name=payload.name,
        email=payload.email,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()  # Flushes new_user.id into active transaction

    # 5. Issue Access & Refresh tokens
    access_token = create_access_token(user_id=str(new_user.id))
    raw_refresh_token, refresh_token_hash = create_refresh_token()

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    # 6. Record initial refresh session
    refresh_session = RefreshSession(
        user_id=new_user.id,
        token_hash=refresh_token_hash,
        device_id=x_device_id,
        expires_at=expires_at,
    )
    db.add(refresh_session)

    logger.info(f"New user registered: {new_user.id} ({phone})")

    return AuthResponse(
        access_token=access_token,
        refresh_token=raw_refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(new_user),
    )


# ==============================================================================
# 4. POST /api/v1/auth/refresh
# ==============================================================================

@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate Refresh Token",
    description="Rotates an existing refresh token, detects token reuse/theft, and returns new access & refresh tokens.",
    responses={
        200: {
            "description": "Tokens successfully rotated.",
            "model": TokenRefreshResponse,
        },
        401: {
            "description": "Invalid, expired, or already-revoked refresh token.",
        },
        403: {
            "description": "Account is deactivated.",
        },
    },
)
async def refresh_tokens(
    payload: TokenRefreshRequest,
    db: SessionDep,
    x_device_id: Optional[str] = Header(
        default=None,
        description="Optional client device identifier",
    ),
) -> TokenRefreshResponse:
    """
    Endpoint handler for POST /api/v1/auth/refresh.
    
    Security Workflow:
    1. Compute SHA-256 hash of submitted refresh token.
    2. Look up session in 'refresh_sessions'.
    3. If token is ALREADY revoked (revoked_at IS NOT NULL) -> Token theft detected!
       Immediately revoke ALL active sessions for that user.
    4. Verify session expiration and user active status.
    5. Generate new access & refresh tokens.
    6. Mark old session revoked and link replaced_by to the new session.
    """
    # 1. Compute SHA-256 hash of submitted refresh token
    token_hash = hash_token(payload.refresh_token)

    # 2. Look up session in PostgreSQL
    result = await db.execute(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_REFRESH_TOKEN",
                "message": "Refresh token is invalid or does not exist.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. 🚨 Token Theft & Reuse Detection
    # If the token exists but was ALREADY revoked/rotated, an attacker is attempting to reuse an old token!
    if session.revoked_at is not None:
        logger.critical(
            f"SECURITY ALERT: Re-use of revoked refresh token detected for user {session.user_id}! Revoking all active sessions."
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        # Invalidate all active sessions for this user immediately
        await db.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == session.user_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_THEFT_DETECTED",
                "message": "Invalid refresh session. For your security, all active sessions have been invalidated.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Check if session has expired
    now = datetime.datetime.now(datetime.timezone.utc)
    if session.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "REFRESH_TOKEN_EXPIRED",
                "message": "Refresh token has expired. Please log in again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 5. Verify user is active
    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_DEACTIVATED",
                "message": "User account is inactive or deleted.",
            },
        )

    # 6. Generate new token pair
    new_access_token = create_access_token(user_id=str(session.user_id))
    raw_new_refresh, new_refresh_hash = create_refresh_token()

    new_expires_at = now + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    # 7. Create new session row
    new_session = RefreshSession(
        id=uuid.uuid4(),
        user_id=session.user_id,
        token_hash=new_refresh_hash,
        device_id=x_device_id or session.device_id,
        expires_at=new_expires_at,
    )
    db.add(new_session)
    await db.flush()

    # 8. Mark old session as revoked and link replaced_by
    session.revoked_at = now
    session.replaced_by = new_session.id

    logger.info(f"Refreshed session for user {session.user_id}. Old session rotated.")

    return TokenRefreshResponse(
        access_token=new_access_token,
        refresh_token=raw_new_refresh,
        token_type="bearer",
    )


# ==============================================================================
# 5. GET /api/v1/auth/me
# ==============================================================================

@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Current User Profile",
    description="Fetches the authenticated user's profile using their Bearer access token.",
    responses={
        200: {
            "description": "User profile retrieved successfully.",
            "model": UserResponse,
        },
        401: {
            "description": "Missing, invalid, or expired access token.",
        },
    },
)
async def get_me(
    current_user: CurrentUserDep,
) -> UserResponse:
    """
    Endpoint handler for GET /api/v1/auth/me.
    Returns the authenticated user's profile information.
    """
    return UserResponse.model_validate(current_user)
