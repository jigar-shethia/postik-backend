"""
Core Configuration Module
=========================
This file loads and validates all environment variables and configuration settings 
for the application using Pydantic Settings.

Beginner Concepts:
------------------
1. **Environment Variables (.env)**:
   Sensitive information (like database passwords and secret keys) should NEVER be 
   hardcoded in your code. Instead, we keep them in a `.env` file and load them at runtime.

2. **Pydantic BaseSettings**:
   Pydantic automatically reads environment variables from your OS or a `.env` file, 
   converts them to Python data types (e.g., string to int, string to list), and validates them.

3. **Computed Fields**:
   Properties derived automatically from other settings (like building a full database 
   connection URL from server, port, user, and password).
"""

from typing import List, Optional, Union
from pydantic import AnyHttpUrl, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings class.
    Each attribute defined here can be overridden by an environment variable with the same name.
    """

    # --------------------------------------------------------------------------
    # General Project Metadata
    # --------------------------------------------------------------------------
    PROJECT_NAME: str = "Postik API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"  # Base URL prefix for all v1 endpoints (e.g. /api/v1/health)
    ENVIRONMENT: str = "development"  # "development", "staging", or "production"
    DEBUG: bool = True  # Set to False in production for security and performance

    # --------------------------------------------------------------------------
    # CORS (Cross-Origin Resource Sharing)
    # --------------------------------------------------------------------------
    # Controls which frontend websites/apps are allowed to call this API.
    # In development, we allow localhost ports for web & mobile emulators.
    BACKEND_CORS_ORIGINS: List[Union[str, AnyHttpUrl]] = [
        "http://localhost",
        "http://localhost:8000",
        "http://localhost:3000",
    ]

    # --------------------------------------------------------------------------
    # PostgreSQL Database Configuration
    # --------------------------------------------------------------------------
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "postik_db"
    
    # Optional direct database connection string (e.g., provided by cloud hosting)
    DATABASE_URL: Optional[str] = None

    # --------------------------------------------------------------------------
    # Redis Configuration
    # --------------------------------------------------------------------------
    # Redis is an in-memory fast data store used for OTP storage, rate-limiting, and caching.
    REDIS_URL: str = "redis://localhost:6379/0"

    # --------------------------------------------------------------------------
    # Security & JWT (JSON Web Tokens)
    # --------------------------------------------------------------------------
    # Secret key used to cryptographically sign tokens so users cannot tamper with them.
    JWT_SECRET_KEY: str = "insecure-development-secret-key-change-in-production-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    
    # Token expiration lifetimes
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60         # Short-lived token for making authenticated API calls
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30           # Long-lived token used to get a new access token without re-logging in
    REGISTRATION_TOKEN_EXPIRE_MINUTES: int = 10   # Temporary token issued after OTP verification for new users

    # --------------------------------------------------------------------------
    # OTP (One-Time Password) & Rate Limiting Settings
    # --------------------------------------------------------------------------
    OTP_EXPIRE_SECONDS: int = 300       # 5 minutes validity
    OTP_COOLDOWN_SECONDS: int = 60      # Must wait 60s before requesting another OTP

    # --------------------------------------------------------------------------
    # SMS Gateway Configuration
    # --------------------------------------------------------------------------
    SMS_MOCK_MODE: bool = True          # When True, prints OTPs to the console instead of sending real SMS
    SMS_GATEWAY_API_KEY: str = ""

    # --------------------------------------------------------------------------
    # Computed Database URIs
    # --------------------------------------------------------------------------
    @computed_field
    @property
    def ASYNC_DATABASE_URI(self) -> str:
        """
        Builds the asynchronous connection URL for SQLAlchemy + asyncpg.
        Format: postgresql+asyncpg://user:password@host:port/dbname
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field
    @property
    def SYNC_DATABASE_URI(self) -> str:
        """
        Builds the synchronous connection URL for Alembic migration tool.
        Format: postgresql://user:password@host:port/dbname
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # --------------------------------------------------------------------------
    # Validators
    # --------------------------------------------------------------------------
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        """
        Parses comma-separated string from .env into a Python list.
        Example: "http://localhost,http://myfrontend.com" -> ["http://localhost", "http://myfrontend.com"]
        """
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """
        Safety Check: Fail fast on startup if someone attempts to run in production
        with a weak or default JWT secret key.
        """
        if self.ENVIRONMENT == "production":
            if (
                not self.JWT_SECRET_KEY
                or "insecure" in self.JWT_SECRET_KEY.lower()
                or len(self.JWT_SECRET_KEY) < 32
            ):
                raise ValueError(
                    "CRITICAL SECURITY ERROR: Production mode requires a strong, random "
                    "JWT_SECRET_KEY with at least 32 characters."
                )
        return self

    # Configuration for Pydantic Settings
    model_config = SettingsConfigDict(
        env_file=".env",              # Automatically search for and read .env
        env_file_encoding="utf-8",
        case_sensitive=True,          # Environment variable names must match case
        extra="ignore",               # Ignore extra variables in .env without crashing
    )


# Create a single global instance of Settings to be imported throughout the app
settings = Settings()
