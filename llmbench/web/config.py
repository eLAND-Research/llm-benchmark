"""Web service configuration."""
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class WebConfig(BaseModel):
    """Web service configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    database_path: str = "llmbench.db"
    max_concurrent_benchmarks: int = 3
    auto_delete_after_days: Optional[int] = None
    upload_max_size_mb: int = 10
    results_base_path: str = "results/web/"
    keep_json_files: bool = True


# Default config instance
config = WebConfig()


def get_database_url() -> str:
    """Get SQLite database URL for SQLAlchemy."""
    db_path = Path(config.database_path).absolute()
    return f"sqlite+aiosqlite:///{db_path}"
