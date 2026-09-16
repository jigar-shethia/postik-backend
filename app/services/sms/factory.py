"""
SMS Provider Factory
====================
This module implements the Factory Pattern to instantiate the appropriate SMS provider 
based on application configuration (`settings.SMS_MOCK_MODE`).

Beginner Concepts:
------------------
1. **Factory Pattern**:
   A design pattern that creates objects without exposing the instantiation logic to the caller.
   Instead of writing `if settings.SMS_MOCK_MODE:` throughout your codebase, you call 
   `get_sms_provider()` and receive the ready-to-use provider instance.
"""

from app.core.config import settings
from app.services.sms.base import BaseSMSProvider
from app.services.sms.mock import MockSMSProvider
from app.services.sms.provider import HttpSMSProvider


def get_sms_provider() -> BaseSMSProvider:
    """
    Factory function returning the active SMS Provider instance.
    - If `settings.SMS_MOCK_MODE` is True -> returns `MockSMSProvider` (console logger).
    - If `settings.SMS_MOCK_MODE` is False -> returns `HttpSMSProvider` (live gateway client).
    """
    if settings.SMS_MOCK_MODE:
        return MockSMSProvider()
    return HttpSMSProvider()
