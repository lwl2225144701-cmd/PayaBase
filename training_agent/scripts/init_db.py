import asyncio
from sqlalchemy import create_engine, text

from core.config import settings
from models.db import Base, RUNTIME_SCHEMA_PATCHES
from models.tables import (
    Tenant,
    Department,
    User,
    KnowledgeBase,
    Document,
    Chunk,
    Conversation,
    Message,
    QueryLog,
    UploadFile,
    PPTTask,
    PDFTask,
    SegmentAttachmentBinding,
    OAuthToken,
)


def init_db():
    engine = create_engine(settings.sync_database_url)

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS vector vector(512)"))
        for sql in RUNTIME_SCHEMA_PATCHES:
            conn.execute(text(sql))
        conn.commit()

    print("Database initialized successfully")


def add_vector_column():
    """Add vector column to chunks table if not exists."""
    engine = create_engine(settings.sync_database_url)

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'chunks' AND column_name = 'vector'
        """))
        if not result.fetchall():
            conn.execute(text("ALTER TABLE chunks ADD COLUMN vector vector(512)"))
            conn.commit()
            print("Vector column added to chunks table")
        else:
            print("Vector column already exists")


if __name__ == "__main__":
    init_db()
    add_vector_column()


if __name__ == "__main__":
    init_db()
