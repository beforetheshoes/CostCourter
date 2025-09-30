from __future__ import annotations

from celery import Task, shared_task


@shared_task(bind=True, name="tasks.ping")
def ping(self: Task) -> str:
    """Simple ping task used for smoke tests."""
    return "pong"
