"""Database logging handler for benchmark execution."""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from .models import BenchmarkLog


class BenchmarkLogHandler(logging.Handler):
    """Custom logging handler that writes to database."""

    def __init__(self, session: AsyncSession, benchmark_id: int):
        super().__init__()
        self.session = session
        self.benchmark_id = benchmark_id
        self.logs_buffer = []

    def emit(self, record: logging.LogRecord):
        """Emit a log record to the database."""
        try:
            # Buffer the log instead of writing immediately for performance
            log_entry = BenchmarkLog(
                benchmark_id=self.benchmark_id,
                timestamp=datetime.utcnow(),
                level=record.levelname,
                message=self.format(record),
                source=record.name,
            )
            self.logs_buffer.append(log_entry)

            # Flush buffer if it gets large
            if len(self.logs_buffer) >= 10:
                self._flush_sync()

        except Exception:
            self.handleError(record)

    def _flush_sync(self):
        """Flush buffered logs to database (synchronous helper)."""
        if self.logs_buffer:
            # Note: This is called from sync context, actual DB write happens later
            pass

    async def flush_async(self):
        """Async flush of buffered logs to database."""
        if self.logs_buffer:
            self.session.add_all(self.logs_buffer)
            await self.session.flush()
            self.logs_buffer = []


async def add_log(
    session: AsyncSession,
    benchmark_id: int,
    level: str,
    message: str,
    source: Optional[str] = None
):
    """Add a log entry directly to the database."""
    log = BenchmarkLog(
        benchmark_id=benchmark_id,
        timestamp=datetime.utcnow(),
        level=level,
        message=message,
        source=source or "system",
    )
    session.add(log)
    await session.flush()
