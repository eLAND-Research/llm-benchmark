"""Migration script to add benchmark_logs table."""
import asyncio
from sqlalchemy import text
from .database import AsyncSessionLocal, engine


async def migrate():
    """Add benchmark_logs table."""
    async with engine.begin() as conn:
        # Check if table exists
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='benchmark_logs'")
        )
        if result.fetchone():
            print("✓ benchmark_logs table already exists")
            return

        print("Creating benchmark_logs table...")
        await conn.execute(
            text("""
                CREATE TABLE benchmark_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    benchmark_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    level VARCHAR(20) NOT NULL,
                    message TEXT NOT NULL,
                    source VARCHAR(100),
                    FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id) ON DELETE CASCADE
                )
            """)
        )

        await conn.execute(
            text("CREATE INDEX idx_benchmark_logs_benchmark_id ON benchmark_logs(benchmark_id)")
        )

        await conn.execute(
            text("CREATE INDEX idx_benchmark_logs_timestamp ON benchmark_logs(timestamp)")
        )

        print("✓ Created benchmark_logs table with indexes")

    print("\n✅ Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())
