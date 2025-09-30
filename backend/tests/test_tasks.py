from __future__ import annotations

from app.tasks.example import ping


def test_ping_task_returns_pong() -> None:
    result = ping.run()
    assert result == "pong"
