"""
Async database layer (Stage B1).

One code path, two drivers via DATABASE_URL:
  • production : postgresql+asyncpg://user:pass@host/db   (PostgreSQL)
  • local/CI   : sqlite+aiosqlite:///./data/dsa.db        (default, no Docker needed)

The rest of the app talks to `repo.py`, never to the session directly.
"""

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from models import Base

BASE_DIR = Path(__file__).parent
DEFAULT_SQLITE = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'dsa.db').as_posix()}"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)
_IS_SQLITE = DATABASE_URL.startswith("sqlite")

# For SQLite, make sure the parent dir exists.
if _IS_SQLITE:
    (BASE_DIR / "data").mkdir(exist_ok=True)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    # Pooling matters on Postgres; SQLite ignores most of these.
    pool_pre_ping=not _IS_SQLITE,
    **({} if _IS_SQLITE else {"pool_size": 10, "max_overflow": 20}),
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create tables if they don't exist (greenfield bootstrap).
    Schema *changes* go through Alembic migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ping() -> bool:
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
