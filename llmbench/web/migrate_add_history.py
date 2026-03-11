"""Migration script to add history tracking fields to benchmarks table."""
import asyncio
from sqlalchemy import text
from .database import AsyncSessionLocal, engine


async def migrate():
    """Add parent_uuid and run_number columns to benchmarks table."""
    async with engine.begin() as conn:
        # Check if columns already exist
        result = await conn.execute(
            text("PRAGMA table_info(benchmarks)")
        )
        columns = {row[1] for row in result.fetchall()}

        if 'parent_uuid' not in columns:
            print("Adding parent_uuid column...")
            await conn.execute(
                text("ALTER TABLE benchmarks ADD COLUMN parent_uuid VARCHAR(36)")
            )
            await conn.execute(
                text("CREATE INDEX idx_benchmarks_parent_uuid ON benchmarks(parent_uuid)")
            )
            print("✓ Added parent_uuid column and index")
        else:
            print("✓ parent_uuid column already exists")

        if 'run_number' not in columns:
            print("Adding run_number column...")
            await conn.execute(
                text("ALTER TABLE benchmarks ADD COLUMN run_number INTEGER DEFAULT 1 NOT NULL")
            )
            print("✓ Added run_number column")
        else:
            print("✓ run_number column already exists")

    print("\n✅ Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())
