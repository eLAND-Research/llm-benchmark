"""Migration: add participant_scores_jsonl column to challenges table."""
import asyncio
from sqlalchemy import text
from .database import engine


async def migrate():
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(challenges)"))
        columns = {row[1] for row in result.fetchall()}

        if "participant_scores_jsonl" not in columns:
            print("Adding participant_scores_jsonl column...")
            await conn.execute(
                text("ALTER TABLE challenges ADD COLUMN participant_scores_jsonl TEXT")
            )
            print("✓ Added participant_scores_jsonl column")
        else:
            print("✓ participant_scores_jsonl already exists")

    print("\n✅ Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(migrate())
