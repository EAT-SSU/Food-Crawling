import hashlib
import io
import json
import logging
from unittest.mock import AsyncMock, patch

from functions import handler


class _Context:
    aws_request_id = "request-123"


def _capture_observation_stream():
    stream = io.StringIO()
    observation_logger = logging.getLogger("food_crawling.observation")
    original_streams = []
    for log_handler in observation_logger.handlers:
        if isinstance(log_handler, logging.StreamHandler):
            original_streams.append((log_handler, log_handler.stream))
            log_handler.setStream(stream)
    return stream, original_streams


def test_source_fingerprint_uses_utf8_length_and_twelve_hex_without_source():
    source = "중식 <html>SECRET_TOKEN"
    source_length, source_sha256 = handler.fingerprint_source(source)
    assert source_length == len(source.encode("utf-8"))
    assert source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    assert "SECRET_TOKEN" not in source_sha256


def test_structured_context_is_reset_between_invocations():
    stream, original_streams = _capture_observation_stream()
    dependencies = (
        patch.object(handler, "scrape", AsyncMock(return_value=[])),
        patch.object(handler, "notify_slack", AsyncMock()),
    )
    try:
        with dependencies[0], dependencies[1]:
            handler.lambda_handler(
                {"operation": "scrape_dodam", "target_date": "20260713"},
                _Context(),
            )
            handler.lambda_handler(
                {"operation": "scrape_haksik", "target_date": "20260714"},
                type("Context", (), {"aws_request_id": "request-456"})(),
            )
    finally:
        for log_handler, original_stream in original_streams:
            log_handler.setStream(original_stream)

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    second = [event for event in events if event["faas.invocation_id"] == "request-456"]
    assert second
    assert all(event["restaurant"] == "HAKSIK" for event in second)
    assert all(event["run_id"] == "request-456" for event in second)
