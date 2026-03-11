"""Task manager for tracking and cancelling benchmark tasks."""
import asyncio
from typing import Dict, Optional
from datetime import datetime


class TaskManager:
    """Manages running benchmark tasks and handles cancellation."""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._cancel_flags: Dict[str, bool] = {}

    def register_task(self, benchmark_uuid: str, task: asyncio.Task):
        """Register a running task."""
        self._tasks[benchmark_uuid] = task
        self._cancel_flags[benchmark_uuid] = False

    def cancel_task(self, benchmark_uuid: str) -> bool:
        """Request cancellation of a task.

        Returns:
            True if task was found and cancellation requested, False otherwise
        """
        if benchmark_uuid in self._cancel_flags:
            self._cancel_flags[benchmark_uuid] = True

            # Also try to cancel the asyncio task directly
            if benchmark_uuid in self._tasks:
                task = self._tasks[benchmark_uuid]
                if not task.done():
                    task.cancel()

            return True
        return False

    def is_cancelled(self, benchmark_uuid: str) -> bool:
        """Check if a task has been cancelled."""
        return self._cancel_flags.get(benchmark_uuid, False)

    def cleanup_task(self, benchmark_uuid: str):
        """Clean up task after completion."""
        self._tasks.pop(benchmark_uuid, None)
        self._cancel_flags.pop(benchmark_uuid, None)

    def get_running_tasks(self) -> Dict[str, asyncio.Task]:
        """Get all currently running tasks."""
        return {
            uuid: task
            for uuid, task in self._tasks.items()
            if not task.done()
        }


# Global task manager instance
task_manager = TaskManager()
