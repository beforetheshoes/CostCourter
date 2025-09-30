from __future__ import annotations

import logging

import pytest
import structlog

from app.core.logging import configure_logging


def test_configure_logging_routes_structlog_to_standard_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    configure_logging()

    logger = structlog.get_logger("test")
    logger.info("hello", feature="logging")

    assert any("hello" in record.getMessage() for record in caplog.records)
    assert any("feature" in record.getMessage() for record in caplog.records)
