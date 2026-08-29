from typing import Annotated, AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_db

# Dependency type alias for endpoints
SessionDep = Annotated[AsyncSession, Depends(get_async_db)]

