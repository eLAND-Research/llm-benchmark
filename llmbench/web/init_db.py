"""Database initialization script."""
import asyncio
from pathlib import Path
from .database import init_db, drop_db, engine
from .config import config
# Import models to register them with Base
from . import models  # noqa: F401


async def initialize_database(drop_existing: bool = False):
    """Initialize the database schema."""
    db_path = Path(config.database_path)

    if drop_existing and db_path.exists():
        print(f"Dropping existing database: {db_path}")
        await drop_db()

    print(f"Creating database at: {db_path}")
    await init_db()
    print("✅ Database initialized successfully!")

    # Enable WAL mode for better concurrency
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.commit()
    print("✅ WAL mode enabled")


async def main():
    """Run database initialization."""
    import sys

    drop_existing = "--drop" in sys.argv or "-d" in sys.argv

    if drop_existing:
        confirm = input("⚠️  This will drop all existing data. Continue? (yes/no): ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return

    await initialize_database(drop_existing=drop_existing)


if __name__ == "__main__":
    asyncio.run(main())
