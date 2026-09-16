"""
Authentication API Endpoints
============================
This module implements the routes for phone-first authentication:
- `POST /api/v1/auth/otp/send`: Request a one-time verification SMS code.
- `POST /api/v1/auth/otp/verify`: Verify submitted OTP and issue tokens / registration flow.

Beginner Concepts:
------------------
1. **Branching Auth Flow (New vs. Existing User)**:
   In a phone-first architecture, the user doesn't choose between "Login" and "Sign Up" buttons upfront.
   They simply enter their phone number.
   - If the phone exists in the `users` table -> Log in directly by issuing an Access + Refresh token pair.
   - If the phone is new -> Issue a scoped `registration_token` granting permission to complete profile registration.

2. **Session Persistence**:
   For existing users, we create a record in `refresh_sessions` storing `SHA-256(refresh_token)`
   so the session can be tracked, rotated, or revoked on the server.
"""

import datetime
import logging
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import RedisDep, SessionDep
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_registration_token,
)
from app.models.session import RefreshSession
from app.models.user import User
from app.schemas.auth import (
    SendOTPRequest,
    SendOTPResponse,
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
