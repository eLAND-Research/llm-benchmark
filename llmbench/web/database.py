"""Database setup and session management."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import get_database_url

# Create async engine
engine = create_async_engine(
    get_database_url(),
    echo=False,  # Set to True for SQL logging
    connect_args={"check_same_thread": False},  # SQLite specific
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add new columns to existing databases (SQLite doesn't support IF NOT EXISTS for columns)
        for sql in [
            "ALTER TABLE challenges ADD COLUMN results_jsonl TEXT",
        ]:
            try:
                await conn.execute(__import__("sqlalchemy").text(sql))
            except Exception:
                pass  # Column already exists


async def drop_db():
    """Drop all database tables (for testing)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
