"""
Mock SMS Provider (Development & Testing)
=========================================
This provider simulates SMS delivery by logging the message to the console instead
of making real paid SMS network calls.

Beginner Concepts:
------------------
1. **Mocking External Services**:
   During local development and automated testing, you do not want to spend money on real 
   SMS gateways or wait for real telecommunications carrier delivery.
   `MockSMSProvider` logs the 6-digit OTP directly to your terminal screen so you can 
   easily copy-paste it into your frontend or API client (Postman/Swagger).
"""

import logging
from app.services.sms.base import BaseSMSProvider

logger = logging.getLogger("sms.mock")


class MockSMSProvider(BaseSMSProvider):
    """
    Mock implementation of BaseSMSProvider that logs SMS messages to the console.
    """

    async def send_sms(self, phone: str, message: str) -> bool:
        """
        Simulates SMS delivery by printing a structured log message.
        Always returns True to indicate successful mock delivery.
        """
        separator = "=" * 60
        log_message = (
            f"\n{separator}\n"
            f"[MOCK SMS GATEWAY DISPATCH]\n"
            f"To      : {phone}\n"
            f"Message : {message}\n"
            f"{separator}"
        )
        # Output as both print (for direct terminal visibility) and logger.info
        print(log_message)
        logger.info(f"[MOCK SMS] To: {phone} | Body: {message}")
        return True
