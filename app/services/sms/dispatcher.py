"""
Safe SMS Dispatch & Persistence Orchestrator
=============================================
This module orchestrates the safe ordering of OTP generation, rate limiting,
external SMS gateway dispatch, and Redis storage.

Beginner Concepts:
------------------
1. **The 'Atomic Dispatch Order' Security Rule**:
   A common backend bug is saving the OTP into the database/cache BEFORE confirming the SMS was 
   actually sent. If the SMS gateway fails (e.g. network timeout, out of credits, carrier error), 
   the database now has an active OTP and a 60-second cooldown lock that the user never actually received!
   
   **Safe Dispatch Order**:
   1. Check rate limits and cooldowns.
   2. Generate 6-digit OTP.
   3. Dispatch SMS via Gateway API.
   4. **ONLY if Gateway responds HTTP 200 (Success):** save OTP hash and activate cooldown in Redis.
   5. If Gateway fails: abort immediately with zero changes to Redis state.
"""

import logging
from typing import Optional, Tuple
from redis.asyncio import Redis

from app.core.config import settings
from app.services.otp_service import check_send_limits, generate_otp, save_otp_hash
from app.services.sms.factory import get_sms_provider

logger = logging.getLogger("sms.dispatcher")


async def send_and_store_otp(
    redis: Redis, phone: str, ip: str
) -> Tuple[bool, Optional[str], int]:
    """
    Orchestrates the entire OTP dispatch workflow safely.
    
    Parameters:
    -----------
    redis : Active Redis client instance.
    phone : Target phone number in E.164 format (e.g. "+1234567890").
    ip    : Client IP address (for rate limiting).
    
    Returns:
    --------
    (success: bool, error_reason: Optional[str], retry_in_seconds: int)
    
    Possible error reasons:
    - "COOLDOWN_ACTIVE"           : 60s resend lock active.
    - "PHONE_RATE_LIMIT_EXCEEDED" : Max 3 attempts in 10 minutes for this phone.
    - "IP_RATE_LIMIT_EXCEEDED"    : Max 20 attempts in 10 minutes for this IP.
    - "SMS_DISPATCH_FAILED"       : SMS Gateway failed to deliver the message.
    """
    # --------------------------------------------------------------------------
    # 1. Rate Limiting & Cooldown Pre-checks
    # --------------------------------------------------------------------------
    allowed, reason, retry_after = await check_send_limits(redis, phone, ip)
    if not allowed:
        logger.warning(
            f"OTP send blocked for phone {phone} (IP: {ip}). Reason: {reason}, Retry in: {retry_after}s"
        )
        return False, reason, retry_after

    # --------------------------------------------------------------------------
    # 2. Cryptographic OTP Generation
    # --------------------------------------------------------------------------
    otp = generate_otp()
    message = f"Your {settings.PROJECT_NAME} verification code is: {otp}. Valid for 5 minutes. Do not share this code."

    # --------------------------------------------------------------------------
    # 3. Dispatch via SMS Provider
    # --------------------------------------------------------------------------
    provider = get_sms_provider()
    dispatch_success = await provider.send_sms(phone, message)

    if not dispatch_success:
        logger.error(
            f"Failed to dispatch SMS to {phone}. Aborting without saving OTP to Redis."
        )
        return False, "SMS_DISPATCH_FAILED", 0

    # --------------------------------------------------------------------------
    # 4. Safe State Persistence in Redis (ONLY executed upon gateway success)
    # --------------------------------------------------------------------------
    await save_otp_hash(
        redis=redis,
        phone=phone,
        otp=otp,
        ttl=settings.OTP_EXPIRE_SECONDS,
        cooldown_ttl=settings.OTP_COOLDOWN_SECONDS,
    )

    logger.info(f"OTP successfully dispatched and persisted for phone {phone}")
    return True, None, settings.OTP_COOLDOWN_SECONDS
