import io
import json
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from functions.lambda_handlers.scheduling.dodam import dodam_schedule_view
from functions.lambda_handlers.scheduling.dormitory import dormitory_schedule_view
from functions.lambda_handlers.scheduling.faculty import faculty_schedule_view
from functions.lambda_handlers.scheduling.haksik import haksik_schedule_view
from functions.lambda_handlers.scraping.dodam import dodam_view
from functions.lambda_handlers.scraping.dormitory import dormitory_view
from functions.lambda_handlers.scraping.faculty import faculty_view
from functions.lambda_handlers.scraping.haksik import haksik_view
from functions.shared.models.exceptions import MenuFetchException, RetryableEmptyMenuError
from functions.shared.models.model import (
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import emit_event, initialize_observation_logger


class _Context:
    def __init__(self, request_id: str):
        self.aws_request_id = request_id


def _parsed(date: str, restaurant: RestaurantType) -> ParsedMenuData:
    return ParsedMenuData(
        date=date,
        restaurant=restaurant,
        menus={"중식1": ["밥"]},
        slot_results={
            "중식1": SlotProcessingResult(
                slot="중식1",
                stage="menu_post",
                outcome=ProcessingOutcome.SUCCESS,
                reason_code="POST_SUCCESS",
            )
        },
    )


def _container(date: str = "20260713"):
    scheduling = SimpleNamespace(
        process_weekly_schedule_general=AsyncMock(return_value=[]),
        process_weekly_schedule_dormitory=AsyncMock(
            return_value=[_parsed(date, RestaurantType.DORMITORY)]
        ),
    )
    scraping = SimpleNamespace(
        scrape_and_process=AsyncMock(),
        scrape_and_process_dormitory=AsyncMock(
            return_value=[_parsed(date, RestaurantType.DORMITORY)]
        ),
    )
    scraping.scrape_and_process.side_effect = lambda target_date, restaurant, **_: _parsed(
        target_date, restaurant
    )
    notification = SimpleNamespace(
        send_date_summary=AsyncMock(return_value=True),
        send_menu_notification=AsyncMock(return_value=True),
        send_error_notification=AsyncMock(return_value=True),
    )
    return SimpleNamespace(
        get_scheduling_service=lambda: scheduling,
        get_scraping_service=lambda: scraping,
        get_notification_service=lambda: notification,
        scheduling=scheduling,
        scraping=scraping,
        notification=notification,
    )


HANDLERS = [
    (dodam_schedule_view, RestaurantType.DODAM),
    (haksik_schedule_view, RestaurantType.HAKSIK),
    (faculty_schedule_view, RestaurantType.FACULTY),
    (dormitory_schedule_view, RestaurantType.DORMITORY),
    (dodam_view, RestaurantType.DODAM),
    (haksik_view, RestaurantType.HAKSIK),
    (faculty_view, RestaurantType.FACULTY),
    (dormitory_view, RestaurantType.DORMITORY),
]


@pytest.mark.parametrize(("handler", "restaurant"), HANDLERS)
def test_all_handlers_bind_correlation_and_reset_context(handler, restaurant):
    output = io.StringIO()
    initialize_observation_logger(output)
    container = _container()
    event = {
        "trigger": "step_functions",
        "execution_id": "execution-stable",
        "retry_count": 2,
        "target_date": "20260713",
    }

    with patch("functions.config.dependencies.get_container", return_value=container):
        handler(event, _Context("invocation-2"))
    emit_event("INFO", "after_invocation", "test")

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    started = next(item for item in events if item["event.name"] == "handler_invocation_started")
    assert started["run_id"] == "execution-stable"
    assert started["faas.invocation_id"] == "invocation-2"
    assert started["retry_count"] == 2
    assert started["restaurant"] == restaurant.english_name
    after = next(item for item in events if item["event.name"] == "after_invocation")
    assert after["run_id"] == "unknown"
    assert after["faas.invocation_id"] == "unknown"
    assert "restaurant" not in after


def test_step_function_retries_keep_run_id_and_increment_retry_count():
    output = io.StringIO()
    initialize_observation_logger(output)
    container = _container()

    with patch("functions.config.dependencies.get_container", return_value=container):
        for retry_count in range(3):
            dormitory_schedule_view(
                {
                    "trigger": "step_functions",
                    "execution_id": "same-execution",
                    "retry_count": retry_count,
                    "target_date": "20260713",
                },
                _Context(f"invocation-{retry_count}"),
            )

    started = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if '"event.name":"handler_invocation_started"' in line
    ]
    assert [item["run_id"] for item in started] == ["same-execution"] * 3
    assert [item["faas.invocation_id"] for item in started] == [
        "invocation-0",
        "invocation-1",
        "invocation-2",
    ]
    assert [item["retry_count"] for item in started] == [0, 1, 2]


@pytest.mark.parametrize(
    "event",
    [
        {"trigger": "direct", "target_date": "20260713", "delayed_schedule": True},
        {"queryStringParameters": {"date": "20260713", "delayed_schedule": "true"}},
    ],
)
def test_general_schedule_accepts_new_and_legacy_direct_invocation(event):
    container = _container()
    with patch("functions.config.dependencies.get_container", return_value=container):
        response = dodam_schedule_view(event, _Context("request"))

    assert response["statusCode"] == 200
    call = container.scheduling.process_weekly_schedule_general.await_args
    assert call.args[:2] == (RestaurantType.DODAM, ["20260713"])


@pytest.mark.parametrize(
    "event",
    [
        {"trigger": "direct", "delayed_schedule": True},
        {"queryStringParameters": {"delayed_schedule": "true"}},
    ],
)
def test_general_schedule_new_and_legacy_delayed_events_use_current_week(event):
    container = _container()
    current_week = ["20260706", "20260707"]
    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch(
            "functions.lambda_handlers.handler_support.get_current_weekdays",
            return_value=current_week,
        ),
    ):
        dodam_schedule_view(event, _Context("request"))

    call = container.scheduling.process_weekly_schedule_general.await_args
    assert call.args[:2] == (RestaurantType.DODAM, current_week)


def test_general_schedule_reraises_unexpected_exception_and_resets_context():
    output = io.StringIO()
    initialize_observation_logger(output)
    container = _container()
    unexpected = RuntimeError("<html>SECRET_TOKEN")
    unexpected.__cause__ = ValueError("provider detail SECRET_TOKEN")
    container.scheduling.process_weekly_schedule_general.side_effect = unexpected

    with patch("functions.config.dependencies.get_container", return_value=container):
        with pytest.raises(Exception) as raised:
            dodam_schedule_view({}, _Context("request"))
    emit_event("INFO", "after_failure", "test")

    text = output.getvalue()
    platform_trace = "".join(
        traceback.format_exception(raised.type, raised.value, raised.tb)
    )
    assert type(raised.value).__name__ == "SanitizedUnhandledError"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "<html>" not in platform_trace
    assert "SECRET_TOKEN" not in platform_trace
    assert "provider detail" not in platform_trace
    assert "SECRET_TOKEN" not in text
    failure_event = next(
        json.loads(line)
        for line in text.splitlines()
        if '"event.name":"handler_invocation_failed"' in line
    )
    assert failure_event["error.type"] == "RuntimeError"
    assert isinstance(failure_event["error.frames"], list)
    after = json.loads(text.splitlines()[-1])
    assert after["run_id"] == "unknown"


@pytest.mark.parametrize(
    "event",
    [
        {"trigger": "direct", "target_date": "20260713"},
        {"queryStringParameters": {"date": "20260713"}},
    ],
)
def test_single_day_scraping_accepts_new_and_legacy_events_and_sends_one_summary(event):
    container = _container()
    with patch("functions.config.dependencies.get_container", return_value=container):
        response = haksik_view(event, _Context("request"))

    assert response["statusCode"] == 200
    call = container.scraping.scrape_and_process.await_args
    assert call.args[:2] == ("20260713", RestaurantType.HAKSIK)
    container.notification.send_date_summary.assert_awaited_once()
    container.notification.send_menu_notification.assert_not_awaited()
    container.notification.send_error_notification.assert_not_awaited()


def test_known_scraping_outcome_sends_one_safe_summary_and_returns_safe_response():
    container = _container()
    container.scraping.scrape_and_process.side_effect = MenuFetchException(
        "20260713", RestaurantType.FACULTY
    )

    with patch("functions.config.dependencies.get_container", return_value=container):
        response = faculty_view(
            {"target_date": "20260713"},
            _Context("request"),
        )

    assert response["statusCode"] == 400
    assert "SECRET_TOKEN" not in str(response["body"])
    summary = container.notification.send_date_summary.await_args.args[0]
    assert summary.date == "20260713"
    assert summary.date_outcome is ProcessingOutcome.AMBIGUOUS_EMPTY
    container.notification.send_date_summary.assert_awaited_once()
    container.notification.send_error_notification.assert_not_awaited()


def test_unexpected_scraping_exception_is_reraised_without_notification():
    container = _container()
    container.scraping.scrape_and_process.side_effect = RuntimeError("SECRET_TOKEN")

    with patch("functions.config.dependencies.get_container", return_value=container):
        with pytest.raises(Exception) as raised:
            dodam_view({"target_date": "20260713"}, _Context("request"))

    platform_trace = "".join(
        traceback.format_exception(raised.type, raised.value, raised.tb)
    )
    assert type(raised.value).__name__ == "SanitizedUnhandledError"
    assert "SECRET_TOKEN" not in platform_trace
    container.notification.send_date_summary.assert_not_awaited()
    container.notification.send_error_notification.assert_not_awaited()


def test_dormitory_retryable_error_identity_survives_handler_boundary():
    container = _container()
    retry_error = RetryableEmptyMenuError(
        "20260713",
        RestaurantType.DORMITORY,
    )
    container.scheduling.process_weekly_schedule_dormitory.side_effect = retry_error

    with patch("functions.config.dependencies.get_container", return_value=container):
        with pytest.raises(RetryableEmptyMenuError) as raised:
            dormitory_schedule_view(
                {"trigger": "step_functions", "target_date": "20260713"},
                _Context("request"),
            )

    assert raised.value is retry_error


def test_dormitory_scraping_handler_uses_single_asyncio_run():
    import asyncio as _asyncio

    container = _container("20260713")
    container.scraping.scrape_and_process_dormitory = AsyncMock(
        return_value=[
            _parsed("20260713", RestaurantType.DORMITORY),
            _parsed("20260714", RestaurantType.DORMITORY),
        ]
    )

    asyncio_run_call_count = 0
    original_asyncio_run = _asyncio.run

    def counting_asyncio_run(coro, **kwargs):
        nonlocal asyncio_run_call_count
        asyncio_run_call_count += 1
        return original_asyncio_run(coro, **kwargs)

    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch(
            "functions.lambda_handlers.handler_support.asyncio.run",
            side_effect=counting_asyncio_run,
        ),
    ):
        response = dormitory_view({"target_date": "20260713"}, _Context("request"))

    assert response["statusCode"] == 200
    assert asyncio_run_call_count == 1, (
        f"Expected exactly 1 asyncio.run() call for the combined scrape-and-notify "
        f"workflow, but got {asyncio_run_call_count}."
    )
    assert container.notification.send_date_summary.await_count == 2


def test_dormitory_scraping_handler_domain_error_uses_single_asyncio_run():
    import asyncio as _asyncio
    from functions.shared.models.exceptions import MenuFetchException

    container = _container()
    container.scraping.scrape_and_process_dormitory.side_effect = MenuFetchException(
        "20260713", RestaurantType.DORMITORY
    )

    asyncio_run_call_count = 0
    original_asyncio_run = _asyncio.run

    def counting_asyncio_run(coro, **kwargs):
        nonlocal asyncio_run_call_count
        asyncio_run_call_count += 1
        return original_asyncio_run(coro, **kwargs)

    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch(
            "functions.lambda_handlers.handler_support.asyncio.run",
            side_effect=counting_asyncio_run,
        ),
    ):
        response = dormitory_view({"target_date": "20260713"}, _Context("request"))

    assert response["statusCode"] == 400
    assert asyncio_run_call_count == 1, (
        f"Expected exactly 1 asyncio.run() call even on domain error path, "
        f"but got {asyncio_run_call_count}."
    )
    container.notification.send_date_summary.assert_awaited_once()
