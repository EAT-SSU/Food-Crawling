import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from functions.lambda_handlers.handler_support import parse_handler_event
from functions.lambda_handlers.notify_failure import notify_failure_handler
from functions.lambda_handlers.scheduling.dodam import dodam_schedule_view
from functions.lambda_handlers.scheduling.dormitory import dormitory_schedule_view
from functions.lambda_handlers.scheduling.faculty import faculty_schedule_view
from functions.lambda_handlers.scheduling.haksik import haksik_schedule_view
from functions.lambda_handlers.scraping.dodam import dodam_view
from functions.lambda_handlers.scraping.dormitory import dormitory_view
from functions.lambda_handlers.scraping.faculty import faculty_view
from functions.lambda_handlers.scraping.haksik import haksik_view
from functions.shared.models.model import (
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import initialize_observation_logger
from functions.shared.services.scheduling_service import SchedulingService
from functions.shared.utils.date_utils import WeekType


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/characterization/invocations.json").read_text(
        encoding="utf-8"
    )
)

RESTAURANTS = {restaurant.english_name: restaurant for restaurant in RestaurantType}
SCRAPE_HANDLERS = {
    "scrape_dodam": dodam_view,
    "scrape_haksik": haksik_view,
    "scrape_faculty": faculty_view,
    "scrape_dormitory": dormitory_view,
}
SCHEDULE_HANDLERS = {
    "schedule_dodam": dodam_schedule_view,
    "schedule_haksik": haksik_schedule_view,
    "schedule_faculty": faculty_schedule_view,
    "schedule_dormitory": dormitory_schedule_view,
}
WEEK_TYPES = {
    "WEEKDAY": WeekType.WEEKDAY,
    "INCLUDE_SATURDAY": WeekType.INCLUDE_SATURDAY,
}


class _Context:
    aws_request_id: str = "characterization-request"


def _parsed(date: str, restaurant: RestaurantType, slot: str = "중식1"):
    return ParsedMenuData(
        date=date,
        restaurant=restaurant,
        menus={slot: ["밥"]},
        slot_results={
            slot: SlotProcessingResult(
                slot=slot,
                stage="menu_post",
                outcome=ProcessingOutcome.SUCCESS,
                reason_code="POST_SUCCESS",
            )
        },
    )


def _container(entry):
    restaurant = RESTAURANTS[entry["restaurant"]]
    date = entry.get("expected_date", "20260713")
    dates = entry.get("current_dates", entry.get("result_dates", [date]))
    parsed = [_parsed(item, restaurant) for item in dates]
    scraping = SimpleNamespace(
        scrape_and_process=AsyncMock(return_value=_parsed(date, restaurant)),
        scrape_and_process_dormitory=AsyncMock(return_value=parsed),
    )
    scheduling = SimpleNamespace(
        process_weekly_schedule_general=AsyncMock(return_value=parsed),
        process_weekly_schedule_dormitory=AsyncMock(return_value=parsed),
    )
    notification = SimpleNamespace(send_date_summary=AsyncMock(return_value=True))
    return SimpleNamespace(
        get_scraping_service=lambda: scraping,
        get_scheduling_service=lambda: scheduling,
        get_notification_service=lambda: notification,
        scraping=scraping,
        scheduling=scheduling,
        notification=notification,
    )


@pytest.mark.parametrize("entry", FIXTURE["operations"], ids=lambda item: item["operation"])
def test_invocation_fixture_parses_internal_and_direct_fields(entry):
    request = parse_handler_event(entry["event"])

    assert request.trigger == entry["event"].get("trigger", "direct")
    assert request.delayed_schedule is entry["event"].get("delayed_schedule", False)
    assert request.execution_id == entry["event"].get("execution_id")
    assert request.retry_count == entry["event"].get("retry_count", 0)
    assert request.target_date == entry.get("expected_date")


@pytest.mark.parametrize(
    "entry",
    [item for item in FIXTURE["operations"] if item["kind"] == "scrape"],
    ids=lambda item: item["operation"],
)
def test_direct_scrape_contracts_response_date_and_slack_count(entry):
    container = _container(entry)
    handler = SCRAPE_HANDLERS[entry["operation"]]

    with patch("functions.config.dependencies.get_container", return_value=container):
        response = handler(entry["event"], _Context())

    assert response["statusCode"] == entry["expected_status"]
    assert response["headers"] == {"Content-Type": "application/json; charset=utf-8"}
    body = json.loads(cast(str, response["body"]))
    assert body["success"] is True
    assert body["restaurant"] == RESTAURANTS[entry["restaurant"]].korean_name
    assert container.notification.send_date_summary.await_count == entry["expected_slack_count"]
    if entry["restaurant"] == "DORMITORY":
        container.scraping.scrape_and_process_dormitory.assert_awaited_once_with(
            entry["expected_date"]
        )
    else:
        container.scraping.scrape_and_process.assert_awaited_once_with(
            entry["expected_date"], RESTAURANTS[entry["restaurant"]]
        )


@pytest.mark.parametrize(
    "entry",
    [item for item in FIXTURE["operations"] if item["kind"] == "schedule"],
    ids=lambda item: item["operation"],
)
def test_scheduled_contracts_dates_prod_flag_and_response(entry):
    container = _container(entry)
    handler = SCHEDULE_HANDLERS[entry["operation"]]

    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch(
            "functions.lambda_handlers.handler_support.get_current_weekdays",
            return_value=entry["current_dates"],
        ),
        patch(
            "functions.lambda_handlers.handler_support.get_next_weekdays",
            return_value=entry.get("next_dates", entry["current_dates"]),
        ),
    ):
        response = handler(entry["event"], _Context())

    assert response["statusCode"] == entry["expected_status"]
    assert response["headers"] == {"Content-Type": "application/json; charset=utf-8"}
    if entry["restaurant"] == "DORMITORY":
        container.scheduling.process_weekly_schedule_dormitory.assert_awaited_once_with(
            entry["current_dates"], is_dev=False
        )
    else:
        container.scheduling.process_weekly_schedule_general.assert_awaited_once_with(
            RESTAURANTS[entry["restaurant"]], entry["next_dates"], is_dev=False
        )


@pytest.mark.parametrize(
    "entry",
    [
        item
        for item in FIXTURE["operations"]
        if item["kind"] == "schedule" and "manual_event" in item
    ],
    ids=lambda item: item["operation"],
)
def test_delayed_manual_schedule_uses_current_date_range(entry):
    container = _container(entry)
    handler = SCHEDULE_HANDLERS[entry["operation"]]

    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch(
            "functions.lambda_handlers.handler_support.get_current_weekdays",
            return_value=entry["current_dates"],
        ),
    ):
        handler(entry["manual_event"], _Context())

    container.scheduling.process_weekly_schedule_general.assert_awaited_once_with(
        RESTAURANTS[entry["restaurant"]], entry["current_dates"], is_dev=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry",
    [item for item in FIXTURE["operations"] if item["kind"] == "schedule"],
    ids=lambda item: item["operation"],
)
async def test_schedule_slack_cardinality_is_one_summary_per_processed_date(entry):
    restaurant = RESTAURANTS[entry["restaurant"]]
    dates = entry["current_dates"]
    notification = SimpleNamespace(send_date_summary=AsyncMock(return_value=True))
    scraping = SimpleNamespace(
        scrape_and_process=AsyncMock(
            side_effect=lambda date, restaurant_type, **_: _parsed(date, restaurant_type)
        ),
        scrape_and_process_dormitory=AsyncMock(
            return_value=[_parsed(date, restaurant, "중식") for date in dates]
        ),
    )
    service = SchedulingService(notification, scraping)

    if restaurant is RestaurantType.DORMITORY:
        await service.process_weekly_schedule_dormitory(dates, is_dev=False)
    else:
        await service.process_weekly_schedule_general(restaurant, dates, is_dev=False)

    assert notification.send_date_summary.await_count == entry["expected_slack_count"]


def test_final_failure_is_pathless_slack_only_response_contract():
    entry = FIXTURE["final_failure"]
    notification = SimpleNamespace(send_date_summary=AsyncMock(return_value=True))
    container = SimpleNamespace(get_notification_service=lambda: notification)

    with patch("functions.config.dependencies.get_container", return_value=container):
        response = notify_failure_handler(entry["event"], _Context())

    assert response["statusCode"] == 200
    assert json.loads(cast(str, response["body"])) == {
        "message": "final failure notified",
        "error_type": "RetryableEmptyMenuError",
    }
    notification.send_date_summary.assert_awaited_once()


def test_legacy_event_parser_ignores_operation_metadata_and_defaults_missing_fields():
    """Legacy operation selection is the invoked Lambda resource, not event data."""
    unknown, missing = FIXTURE["invalid"]
    event_without_operation = unknown["event"]
    event_with_unknown_operation = {
        **event_without_operation,
        "operation": unknown["operation"],
    }

    assert parse_handler_event(event_with_unknown_operation) == parse_handler_event(
        event_without_operation
    )
    unknown_request = parse_handler_event(event_with_unknown_operation)
    assert unknown_request.trigger == "direct"
    assert unknown_request.delayed_schedule is False
    assert unknown_request.execution_id is None
    assert unknown_request.retry_count == 0
    assert unknown_request.target_date == "20260713"

    missing_request = parse_handler_event(missing["event"])
    assert missing_request.trigger == "direct"
    assert missing_request.delayed_schedule is False
    assert missing_request.execution_id is None
    assert missing_request.retry_count == 0
    assert missing_request.target_date is None


def test_null_query_map_and_observability_correlation_are_stable():
    entry = FIXTURE["operations"][0]
    container = _container(entry)
    output = io.StringIO()
    initialize_observation_logger(output)

    with patch("functions.config.dependencies.get_container", return_value=container):
        response = dodam_view(entry["event"], _Context())

    emitted = [json.loads(line) for line in output.getvalue().splitlines()]
    started = next(item for item in emitted if item["event.name"] == "handler_invocation_started")
    assert response["statusCode"] == 200
    assert started["trigger"] == "iam"
    assert started["date"] == "20260713"
    assert started["faas.invocation_id"] == _Context.aws_request_id
