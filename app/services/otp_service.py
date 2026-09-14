"""
OTP (One-Time Password) & Rate-Limiting Service
===============================================
This module handles secure OTP generation, cryptographic SHA-256 hashing,
multi-tier abuse prevention (phone cooldowns, phone rate limits, IP rate limits),
and brute-force attempt defense using Redis.

Beginner Concepts:
------------------
1. **Why Cryptographic Hashing for OTPs?**:
   If an unauthorized party gains read access to Redis memory dumps, storing plain OTPs
   like '123456' allows them to intercept user logins.
   By storing `SHA-256('123456')`, the OTP cannot be reversed from memory.

2. **Timing Attack Protection (`hmac.compare_digest`)**:
   Standard string comparison (`a == b`) terminates early at the first mismatched character.
   Attackers can measure subtle nanosecond timing differences to guess the secret digit by digit.
   `hmac.compare_digest` runs in constant time regardless of where differences occur.

3. **Multi-Tier Rate Limiting**:
   - **Cooldown (60s)**: Stops a user from spamming the "Send OTP" button repeatedly.
   - **Phone Limit (3 per 10m)**: Prevents toll fraud / SMS cost abuse against a single phone number.
   - **IP Limit (20 per 10m)**: Prevents an automated bot script from triggering thousands of SMS
     messages across many numbers from a single IP address.

4. **Brute-Force Lockout**:
   Since a 6-digit OTP has only 1,000,000 possibilities, an automated script could test all
   possibilities in minutes. Limiting verification to 5 failed attempts and immediately deleting
   the OTP eliminates brute-force vulnerability.
"""

import hashlib
import hmac
import logging
import secrets
from typing import Optional, Tuple
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Constants for Rate Limiting
PHONE_RATE_LIMIT_MAX = 3       # Maximum OTP requests per phone per window
PHONE_RATE_LIMIT_WINDOW = 600  # 10 minutes (in seconds)
IP_RATE_LIMIT_MAX = 20         # Maximum OTP requests per IP per window
IP_RATE_LIMIT_WINDOW = 600     # 10 minutes (in seconds)
MAX_VERIFY_ATTEMPTS = 5        # Maximum wrong OTP attempts before auto-wipe


def hash_secret(value: str) -> str:
    """
    Computes an irreversible SHA-256 hexadecimal digest of a secret string.
    
    Example:
    --------
    >>> hash_secret("123456")
    '8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92'
    """
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def generate_otp() -> str:
    """
    Generates a cryptographically secure 6-digit OTP string between '100000' and '999999'.
    Uses `secrets` instead of standard `random` to ensure true unpredictability.
    """
    # secrets.randbelow(900000) generates [0, 899999]. Adding 100000 ensures 6 digits.
    code = secrets.randbelow(900000) + 100000
    return str(code)


async def check_send_limits(
    redis: Redis, phone: str, ip: str
) -> Tuple[bool, Optional[str], int]:
    """
    Checks whether a new OTP can be sent to the given phone number and client IP.
    
    Returns:
    --------
    (allowed: bool, reason: Optional[str], retry_after_seconds: int)
    
    Checks performed:
    1. Cooldown Lock: Has 60 seconds passed since the last OTP for this phone?
    2. Phone Limit: Has this phone requested <= 3 OTPs in the last 10 minutes?
    3. IP Limit: Has this IP requested <= 20 OTPs in the last 10 minutes?
    """
    cooldown_key = f"cooldown:otp:{phone}"
    phone_rate_key = f"rate:otp_phone:{phone}"
    ip_rate_key = f"rate:otp_ip:{ip}"

    # 1. Check 60s cooldown lock
    cooldown_ttl = await redis.ttl(cooldown_key)
    if cooldown_ttl > 0:
        return False, "COOLDOWN_ACTIVE", cooldown_ttl

    # 2. Check Phone Rate Limit (max 3 / 10m)
    current_phone_count = await redis.get(phone_rate_key)
    if current_phone_count and int(current_phone_count) >= PHONE_RATE_LIMIT_MAX:
        ttl = await redis.ttl(phone_rate_key)
        return False, "PHONE_RATE_LIMIT_EXCEEDED", max(ttl, 1)

    # 3. Check IP Rate Limit (max 20 / 10m)
    current_ip_count = await redis.get(ip_rate_key)
    if current_ip_count and int(current_ip_count) >= IP_RATE_LIMIT_MAX:
        ttl = await redis.ttl(ip_rate_key)
        return False, "IP_RATE_LIMIT_EXCEEDED", max(ttl, 1)

    # Increment rate counters atomically
    phone_count = await redis.incr(phone_rate_key)
    if phone_count == 1:
        await redis.expire(phone_rate_key, PHONE_RATE_LIMIT_WINDOW)

    ip_count = await redis.incr(ip_rate_key)
    if ip_count == 1:
        await redis.expire(ip_rate_key, IP_RATE_LIMIT_WINDOW)

    return True, None, 0


async def save_otp_hash(
    redis: Redis,
    phone: str,
    otp: str,
    ttl: Optional[int] = None,
    cooldown_ttl: Optional[int] = None,
) -> None:
    """
    Stores the SHA-256 hash of the OTP in Redis along with cooldown and attempt counters.
    
    Parameters:
    -----------
    redis        : Async Redis client.
    phone        : E.164 phone number.
    otp          : Raw 6-digit OTP (hashed before storage).
    ttl          : Expiration time for OTP validity (defaults to OTP_EXPIRE_SECONDS = 300s).
    cooldown_ttl : Expiration time for resend cooldown (defaults to OTP_COOLDOWN_SECONDS = 60s).
    """
    expire_seconds = ttl or settings.OTP_EXPIRE_SECONDS
    cooldown_seconds = cooldown_ttl or settings.OTP_COOLDOWN_SECONDS

    otp_key = f"otp:{phone}"
    cooldown_key = f"cooldown:otp:{phone}"
    attempts_key = f"otp_attempts:{phone}"

    # Compute SHA-256 hash of OTP
    hashed_otp = hash_secret(otp)

    # Store hashed OTP with 5-minute TTL
    await redis.set(otp_key, hashed_otp, ex=expire_seconds)

    # Set 60-second cooldown lock
    await redis.set(cooldown_key, "1", ex=cooldown_seconds)

    # Reset/initialize failed attempts counter
    await redis.set(attempts_key, "0", ex=expire_seconds)

    logger.info(f"OTP hash stored for phone {phone} (TTL: {expire_seconds}s)")


async def verify_otp_hash(
    redis: Redis,
    phone: str,
    submitted_otp: str,
) -> Tuple[bool, str]:
    """
    Verifies a user-submitted OTP against the stored SHA-256 hash in Redis.
    
    Returns:
    --------
    (is_valid: bool, status_code_str: str)
    
    Status codes:
    - "VALID"                  : OTP is correct and consumed.
    - "EXPIRED_OR_NOT_FOUND"   : No active OTP found for this phone number.
    - "MAX_ATTEMPTS_EXCEEDED"  : Exceeded 5 failed attempts; OTP was wiped for security.
    - "INVALID_OTP"            : Wrong OTP entered; remaining attempts decremented.
    """
    otp_key = f"otp:{phone}"
    attempts_key = f"otp_attempts:{phone}"

    # 1. Fetch stored SHA-256 hash
    stored_hash = await redis.get(otp_key)
    if not stored_hash:
        return False, "EXPIRED_OR_NOT_FOUND"

    # 2. Increment and check attempt count
    attempts = await redis.incr(attempts_key)
    if attempts > MAX_VERIFY_ATTEMPTS:
        # Wipe OTP immediately to prevent further brute-force attacks
        await redis.delete(otp_key, attempts_key)
        logger.warning(f"Max OTP attempts exceeded for {phone}. OTP destroyed.")
        return False, "MAX_ATTEMPTS_EXCEEDED"

    # 3. Compute hash of user input
    submitted_hash = hash_secret(submitted_otp)

    # 4. Compare digests in constant time (prevents timing side-channel attacks)
    if hmac.compare_digest(submitted_hash, stored_hash):
        # Verification succeeded -> Delete OTP so it cannot be used a second time
        await redis.delete(otp_key, attempts_key)
        logger.info(f"OTP verified successfully for phone {phone}")
        return True, "VALID"

    logger.warning(
        f"Invalid OTP attempt {attempts}/{MAX_VERIFY_ATTEMPTS} for phone {phone}"
    )
    return False, "INVALID_OTP"
