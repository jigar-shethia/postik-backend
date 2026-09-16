"""
Authentication API Endpoints
============================
This module implements the routes for phone-first authentication:
- `POST /api/v1/auth/otp/send`: Request a one-time verification SMS code.

Beginner Concepts:
------------------
1. **Client IP Extraction Behind Proxies (`X-Forwarded-For`)**:
   When your API runs in production behind a reverse proxy (like Cloudflare, Nginx, or AWS Load Balancer), 
   `request.client.host` would see the proxy's IP address instead of the real user's device IP.
   Reading `X-Forwarded-For` extracts the real client IP for accurate rate limiting.

2. **HTTP 429 Too Many Requests & `Retry-After` Header**:
   RFC standards dictate that when a client hits a rate limit, the server should return HTTP 429 
   along with a `Retry-After: <seconds>` header telling the client mobile app exactly how many 
   seconds to display in their cooldown countdown timer (e.g. "Resend in 48s").
"""

import logging
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import RedisDep
from app.schemas.auth import SendOTPRequest, SendOTPResponse
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
