"""
Authentication & User Schemas (Pydantic DTOs)
==============================================
This module defines the validation models for request payloads and response DTOs 
in the authentication and user onboarding flows.

Beginner Concepts:
------------------
1. **Input Sanitization & Validation**:
   - **E.164 Phone Format (`^\\+[1-9]\\d{7,14}$`)**: Ensures international phone numbers 
     include country codes (e.g. "+14155552671" or "+919876543210") and contain no invalid symbols.
   - **OTP Format (`^\\d{6}$`)**: Ensures the OTP is strictly a 6-digit numeric string.
   - **Whitespace Stripping (`field_validator`)**: Removes accidental leading/trailing spaces from names.

2. **Pydantic `from_attributes = True`**:
   Allows Pydantic to read directly from SQLAlchemy ORM model objects (e.g. `UserResponse.model_validate(user)`).

3. **HTTP 422 Unprocessable Entity**:
   If a client sends an invalid phone number or a 5-digit OTP, FastAPI automatically rejects 
   the request before your route handler runs, with clear structured error messages.
"""

import datetime
import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# E.164 standard: '+' followed by 1-3 digit country code and 7-14 subscriber digits (total 8-15 digits)
E164_PHONE_REGEX = r"^\+[1-9]\d{7,14}$"

# Exact 6-digit numerical code
OTP_REGEX = r"^\d{6}$"


# ==============================================================================
# 1. Send OTP Schemas
# ==============================================================================

class SendOTPRequest(BaseModel):
    """
    Request payload for POST /api/v1/auth/otp/send.
    """
    phone: str = Field(
        ...,
        pattern=E164_PHONE_REGEX,
        description="User phone number in international E.164 format (e.g. +14155552671)",
        examples=["+14155552671", "+919876543210"],
    )


class SendOTPResponse(BaseModel):
    """
    Response model for POST /api/v1/auth/otp/send.
    """
    message: str = "OTP sent successfully"
    retry_in_seconds: int = 60


# ==============================================================================
# 2. Verify OTP Schemas
# ==============================================================================

class VerifyOTPRequest(BaseModel):
    """
    Request payload for POST /api/v1/auth/otp/verify.
    """
    phone: str = Field(
        ...,
        pattern=E164_PHONE_REGEX,
        description="User phone number in international E.164 format",
        examples=["+14155552671"],
    )
    otp: str = Field(
        ...,
        pattern=OTP_REGEX,
        description="6-digit verification code",
        examples=["123456"],
    )


class VerifyOTPResponse(BaseModel):
    """
    Response model for POST /api/v1/auth/otp/verify.
    - If is_new_user is True: returns temporary registration_token.
    - If is_new_user is False: returns access_token + refresh_token.
    """
    is_new_user: bool
    registration_token: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = "bearer"


# ==============================================================================
# 3. User Registration Schemas
# ==============================================================================

class RegisterRequest(BaseModel):
    """
    Request payload for POST /api/v1/auth/register.
    Requires Bearer <registration_token> in the Authorization header.
    """
    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Customer's full name (for delivery orders)",
        examples=["Jane Doe"],
    )
    email: Optional[EmailStr] = Field(
        default=None,
        description="Optional customer email address",
        examples=["jane.doe@example.com"],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Strips leading/trailing whitespace and ensures name is not purely blank."""
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("Name must contain at least 2 non-whitespace characters.")
        return stripped


# ==============================================================================
# 4. Token Refresh Schemas
# ==============================================================================

class TokenRefreshRequest(BaseModel):
    """
    Request payload for POST /api/v1/auth/refresh.
    """
    refresh_token: str = Field(
        ...,
        min_length=10,
        description="The raw refresh token previously issued to the client",
    )


class TokenRefreshResponse(BaseModel):
    """
    Response model for POST /api/v1/auth/refresh.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ==============================================================================
# 5. User Profile Responses
# ==============================================================================

class UserResponse(BaseModel):
    """
    Safe public representation of a User profile.
    """
    id: uuid.UUID
    phone: str
    name: str
    email: Optional[str] = None
    is_active: bool
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    """
    Full authentication response containing tokens and the user profile.
    Returned on successful registration.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
