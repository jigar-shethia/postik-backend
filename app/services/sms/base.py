"""
Abstract SMS Provider Base Class
================================
This module defines the abstract interface that all SMS providers must implement.

Beginner Concepts:
------------------
1. **Abstraction & Interfaces (ABC - Abstract Base Classes)**:
   In software architecture, you never want your application logic tightly coupled to a 
   single third-party vendor (like Twilio, AWS SNS, or Fast2SMS).
   By defining a `BaseSMSProvider` abstract contract, our code interacts only with the 
   interface (`send_sms()`). Switching between a free mock provider in local development 
   and a real paid SMS vendor in production requires changing a single config flag, 
   with zero changes to business logic.

2. **Asynchronous Method (`async def`)**:
   Sending an SMS involves making an outbound network HTTP request to an external gateway.
   Making this method asynchronous ensures the server does not block other user requests 
   while waiting for the SMS gateway to respond.
"""

from abc import ABC, abstractmethod


class BaseSMSProvider(ABC):
    """
    Abstract Base Class for SMS delivery providers.
    All concrete SMS providers must subclass this class and implement `send_sms`.
    """

    @abstractmethod
    async def send_sms(self, phone: str, message: str) -> bool:
        """
        Dispatches an SMS text message to the specified phone number.
        
        Parameters:
        -----------
        phone   : E.164 formatted phone number (e.g. "+1234567890").
        message : The text body of the SMS (e.g. "Your Postik verification code is 123456").
        
        Returns:
        --------
        bool : True if the SMS gateway accepted and queued/dispatched the message, False otherwise.
        """
        pass
