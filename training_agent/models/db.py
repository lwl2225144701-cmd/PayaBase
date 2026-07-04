import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


RUNTIME_SCHEMA_PATCHES = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_type VARCHAR(50) DEFAULT 'local'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url VARCHAR(2000)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMP",
]


async def ensure_runtime_schema(conn) -> None:
    for sql in RUNTIME_SCHEMA_PATCHES:
        await conn.execute(text(sql))


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await ensure_runtime_schema(conn)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")
