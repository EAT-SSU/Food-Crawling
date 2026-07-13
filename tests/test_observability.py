import hashlib
import io
import json
from typing import Optional

import pytest

from functions.shared.models.model import (
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import (
    bind_observation_context,
    build_run_id,
    emit_event,
    fingerprint_source,
    initialize_observation_logger,
    measure_duration,
    reset_observation_context,
)


class _LambdaContext:
    aws_request_id = "lambda-request"


def _bind_test_context(
    run_id: str = "execution-456", restaurant: Optional[str] = "DORMITORY"
):
    return bind_observation_context(
        service_name="menu-scraper",
        invocation_id="request-123",
        run_id=run_id,
        restaurant=restaurant,
        trigger="step-functions",
    )


def test_json_event_is_one_object_with_required_fields_and_omits_none():
    output = io.StringIO()
    _ = initialize_observation_logger(stream=output)
    tokens = _bind_test_context()

    try:
        emit_event(
            "INFO",
            "slot.processed",
            "parse",
            slot="lunch",
            outcome=ProcessingOutcome.SUCCESS,
            reason_code=None,
        )
    finally:
        reset_observation_context(tokens)

    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert isinstance(event, dict)
    assert event["service.name"] == "menu-scraper"
    assert event["event.name"] == "slot.processed"
    assert event["faas.invocation_id"] == "request-123"
    assert event["run_id"] == "execution-456"
    assert event["stage"] == "parse"
    assert event["outcome"] == "SUCCESS"
    assert "reason_code" not in event


def test_context_reset_prevents_warm_invocation_leakage():
    output = io.StringIO()
    _ = initialize_observation_logger(stream=output)
    first_tokens = _bind_test_context(run_id="first-run", restaurant="DODAM")
    reset_observation_context(first_tokens)
    second_tokens = _bind_test_context(run_id="second-run", restaurant=None)

    try:
        emit_event("INFO", "invocation.started", "handler")
    finally:
        reset_observation_context(second_tokens)

    event = json.loads(output.getvalue())
    assert event["run_id"] == "second-run"
    assert "restaurant" not in event
    assert "first-run" not in output.getvalue()


def test_logger_initialization_does_not_duplicate_handlers_or_propagate():
    output = io.StringIO()
    logger = initialize_observation_logger(stream=output)
    _ = initialize_observation_logger(stream=output)
    _ = initialize_observation_logger(stream=output)
    tokens = _bind_test_context()

    try:
        emit_event("WARNING", "slot.empty", "classify")
    finally:
        reset_observation_context(tokens)

    assert len(output.getvalue().splitlines()) == 1
    assert len(logger.handlers) == 1
    assert logger.propagate is False


def test_source_fingerprint_uses_utf8_length_and_twelve_hex_without_source():
    source = "중식 <html>SECRET_TOKEN"
    source_length, source_sha256 = fingerprint_source(source)

    assert source_length == len(source.encode("utf-8"))
    assert source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    assert len(source_sha256) == 12
    assert source not in source_sha256
    assert "SECRET_TOKEN" not in source_sha256


def test_measure_duration_uses_monotonic_nanoseconds(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "functions.shared.observability.time.perf_counter_ns", lambda: 2_750_000
    )

    assert measure_duration(1_000_000) == 1.75


def test_build_run_id_precedence_and_request_fallback():
    context = _LambdaContext()

    assert build_run_id(
        {"execution_id": "step-execution", "id": "event-id"}, context
    ) == "step-execution"
    assert build_run_id({"id": "event-id"}, context) == "event-id"
    assert build_run_id({"date": "20260712"}, context) == "lambda-request"


def test_parsed_menu_data_serializes_results_without_exception_payloads():
    result = SlotProcessingResult(
        slot="lunch",
        stage="parse",
        outcome=ProcessingOutcome.PARSER_FAILURE,
        reason_code="EMPTY_MODEL_RESULT",
        source_length=18,
        source_sha256="123456789abc",
        duration_ms=4.5,
        retry_count=2,
        error_type="MenuParseException",
    )
    parsed = ParsedMenuData(
        "20260712",
        RestaurantType.DORMITORY,
        {"lunch": []},
        False,
        {"lunch": ValueError("<html>SECRET_TOKEN")},
        slot_results={"lunch": result},
    )

    serialized = parsed.to_dict()
    json_text = json.dumps(serialized)
    assert serialized["slot_results"]["lunch"]["outcome"] == "PARSER_FAILURE"
    assert serialized["error_slots"] == {"lunch": "ValueError"}
    assert "SECRET_TOKEN" not in json_text


def test_parsed_menu_data_preserves_existing_string_errors_and_positionals():
    parsed = ParsedMenuData(
        "20260712",
        RestaurantType.DORMITORY,
        {"lunch": ["rice"], "dinner": []},
        False,
        {"dinner": "파싱 실패"},
    )

    assert parsed.slot_results == {}
    assert parsed.get_successful_slots() == {"lunch": ["rice"]}
    assert parsed.to_dict()["error_slots"] == {"dinner": "파싱 실패"}
