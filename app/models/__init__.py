"""
Database Models Package
=======================
This package exports all SQLAlchemy ORM models so that Alembic and the application 
can discover all database table definitions automatically.

Beginner Concepts:
------------------
When Alembic runs `alembic revision --autogenerate`, it imports `Base.metadata`.
For Alembic to detect all tables, every model class must be imported into Python 
memory before Alembic inspects the metadata.
"""

from app.db.base import Base, TimestampMixin
from app.models.post import Post
from app.models.session import RefreshSession
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "RefreshSession",
    "Post",
]
