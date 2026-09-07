"""
Sample Post Database Model
==========================
This is an example SQLAlchemy 2.0 database model representing a 'posts' table in PostgreSQL.

Beginner Concepts:
------------------
1. **UUID Primary Keys**:
   Instead of auto-incrementing integer IDs (`1, 2, 3...`), modern distributed applications 
   frequently use UUIDv4 (Universally Unique Identifiers, e.g. `c9bf9e57-1685-4c89-bafb-ff5af830be8a`).
   - Prevents enumeration attacks (attackers guessing URLs like `/user/1`, `/user/2`).
   - Safe for distributed systems and offline client-side ID generation.

2. **Mapped Column Typing (SQLAlchemy 2.0)**:
   `Mapped[str]` provides strict Python type hints while `mapped_column(String(255))` defines the 
   actual column type and constraints in PostgreSQL.
"""

import uuid
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Post(Base, TimestampMixin):
    """
    SQLAlchemy ORM Model representing the 'posts' table in PostgreSQL.
    Inherits created_at and updated_at automatically from TimestampMixin.
    """
    __tablename__ = "posts"

    # UUID Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Post attributes
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(default=False, nullable=False)
