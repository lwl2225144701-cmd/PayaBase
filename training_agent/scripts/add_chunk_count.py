import asyncio
from sqlalchemy import create_engine, text

DB_URL = "postgresql+asyncpg://training:training123@localhost:5432/training_agent"

async def run():
    engine = create_engine(DB_URL.replace("+asyncpg", ""))
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER DEFAULT 0"))
        conn.commit()
    print("Done")

asyncio.run(run())