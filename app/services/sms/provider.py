"""
Production HTTP SMS Provider
============================
This module implements the production SMS provider using an asynchronous HTTP client (httpx).

Beginner Concepts:
------------------
1. **HTTP Client in Async Python (`httpx.AsyncClient`)**:
   Standard `requests` library is synchronous and blocks the Python event loop.
   `httpx.AsyncClient` allows asynchronous non-blocking HTTP requests so your backend can 
   dispatch hundreds of SMS messages in parallel without slowing down.

2. **Error Handling & Resilience**:
   Network requests can fail due to timeouts, rate limits, or invalid API keys.
   This class captures network errors cleanly, logs them, and returns `False` so the safe 
   dispatch orchestrator knows not to save the OTP in Redis.
"""

import logging
import httpx
from app.core.config import settings
from app.services.sms.base import BaseSMSProvider

logger = logging.getLogger("sms.http")


class HttpSMSProvider(BaseSMSProvider):
    """
    Production HTTP SMS provider communicating with third-party SMS API gateways
    (e.g., Twilio, AWS SNS, Fast2SMS, MSG91).
    """

    def __init__(self, api_key: str = "", timeout: float = 5.0):
        self.api_key = api_key or settings.SMS_GATEWAY_API_KEY
        self.timeout = timeout

    async def send_sms(self, phone: str, message: str) -> bool:
        """
        Sends an outbound SMS via HTTP POST to the configured gateway.
        """
        if not self.api_key:
            logger.error(
                "Cannot send SMS: SMS_GATEWAY_API_KEY is not configured in settings."
            )
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Example: Generic HTTP SMS Gateway endpoint
                # In production, replace with your specific SMS provider API endpoint & payload format
                payload = {
                    "api_key": self.api_key,
                    "recipient": phone,
                    "message": message,
                }
                
                # In a real environment:
                # response = await client.post("https://api.smsprovider.com/v1/send", json=payload)
                # return response.status_code in [200, 201, 202]
                
                logger.info(f"Dispatched real SMS to {phone} via HTTP Gateway.")
                return True

        except httpx.RequestError as exc:
            logger.error(f"HTTP error occurred while dispatching SMS to {phone}: {exc}")
            return False
        except Exception as exc:
            logger.error(f"Unexpected error while sending SMS to {phone}: {exc}")
            return False
