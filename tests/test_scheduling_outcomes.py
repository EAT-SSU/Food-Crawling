import traceback
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from functions.shared.models.exceptions import (
    HolidayException,
    MenuFetchException,
    MenuParseException,
    MenuPostException,
    RetryableApiSendError,
    RetryableEmptyMenuError,
)
from functions.shared.models.model import (
    ParsedMenuData,
    ProcessingOutcome,
    RawMenuData,
    RestaurantType,
    SlotProcessingResult,
    TimeSlot,
)
from functions.shared.repositories.clients.slack_client import SlackNotificationError
from functions.shared.services.scheduling_service import SchedulingService
from functions.shared.services.scraping_service import ScrapingService


def _slot(
    slot: str,
    outcome: ProcessingOutcome = ProcessingOutcome.SUCCESS,
    reason_code: str = "POST_SUCCESS",
    stage: str = "menu_post",
) -> SlotProcessingResult:
    return SlotProcessingResult(
        slot=slot,
        stage=stage,
        outcome=outcome,
        reason_code=reason_code,
    )


def _parsed(
    date: str,
    restaurant: RestaurantType = RestaurantType.DODAM,
) -> ParsedMenuData:
    return ParsedMenuData(
        date=date,
        restaurant=restaurant,
        menus={"중식1": ["밥"]},
        slot_results={"중식1": _slot("중식1")},
    )


@pytest.mark.asyncio
async def test_mixed_week_sends_exactly_one_summary_per_date_and_continues_known_failures():
    dates = ["20260713", "20260714", "20260715", "20260716", "20260717"]
    restaurant = RestaurantType.DODAM
    source_failure = MenuFetchException(
        dates[4],
        restaurant,
        reason_code="SOURCE_HTTP_ERROR",
        outcome=ProcessingOutcome.API_FAILURE,
        error_type="TimeoutError",
    )
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process.side_effect = [
        _parsed(dates[0]),
        HolidayException(dates[1], restaurant, "<html>SECRET_TOKEN"),
        MenuParseException(dates[2], restaurant),
        MenuPostException(dates[3], restaurant, "SECRET_TOKEN"),
        source_failure,
    ]
    notification_service = AsyncMock()
    service = SchedulingService(notification_service, scraping_service)

    result = await service.process_weekly_schedule_general(
        restaurant,
        dates,
        is_dev=False,
    )

    assert result == [_parsed(dates[0])]
    assert scraping_service.scrape_and_process.await_count == 5
    assert notification_service.send_date_summary.await_count == 5
    summaries = [call.args[0] for call in notification_service.send_date_summary.await_args_list]
    assert [summary.date for summary in summaries] == dates
    assert summaries[0].slot_results["중식1"].outcome is ProcessingOutcome.SUCCESS
    assert summaries[1].date_outcome is ProcessingOutcome.EXPECTED_EMPTY
    assert summaries[1].reason_code == "HOLIDAY"
    assert next(iter(summaries[2].slot_results.values())).outcome is ProcessingOutcome.PARSER_FAILURE
    assert next(iter(summaries[2].slot_results.values())).reason_code == "PARSE_ERROR"
    assert next(iter(summaries[3].slot_results.values())).outcome is ProcessingOutcome.API_FAILURE
    assert next(iter(summaries[3].slot_results.values())).reason_code == "POST_ERROR"
    fetch_result = next(iter(summaries[4].slot_results.values()))
    assert fetch_result.outcome is ProcessingOutcome.API_FAILURE
    assert fetch_result.reason_code == "SOURCE_HTTP_ERROR"
    assert fetch_result.stage == "source_fetch"
    notification_service.send_menu_notification.assert_not_awaited()
    notification_service.send_error_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_domain_summary_preserves_distinct_source_slot_classifications():
    date = "20260713"
    restaurant = RestaurantType.DORMITORY
    closed = SlotProcessingResult(
        slot="중식",
        stage="source_fetch",
        outcome=ProcessingOutcome.EXPECTED_EMPTY,
        reason_code="CLOSED_MARKER",
        source_length=12,
        source_sha256="abc123def456",
        duration_ms=1.25,
        retry_count=0,
    )
    empty = SlotProcessingResult(
        slot="석식",
        stage="source_parse",
        outcome=ProcessingOutcome.AMBIGUOUS_EMPTY,
        reason_code="EMPTY_CELL",
        source_length=0,
        source_sha256="e3b0c44298fc",
        duration_ms=2.5,
        retry_count=1,
    )
    raw = RawMenuData(
        date,
        restaurant,
        {},
        {"중식": closed, "석식": empty},
    )
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process.side_effect = MenuFetchException(
        date,
        restaurant,
        raw_menu_data=raw,
        error_type="SourceClassificationError",
    )
    notification_service = AsyncMock()
    service = SchedulingService(notification_service, scraping_service)

    await service.process_weekly_schedule_general(restaurant, [date], is_dev=False)

    summary = notification_service.send_date_summary.await_args.args[0]
    preserved_closed = summary.slot_results["중식"]
    preserved_empty = summary.slot_results["석식"]
    assert (
        preserved_closed.stage,
        preserved_closed.outcome,
        preserved_closed.reason_code,
        preserved_closed.source_length,
        preserved_closed.source_sha256,
        preserved_closed.duration_ms,
        preserved_closed.retry_count,
    ) == (
        "source_fetch",
        ProcessingOutcome.EXPECTED_EMPTY,
        "CLOSED_MARKER",
        12,
        "abc123def456",
        1.25,
        0,
    )
    assert (
        preserved_empty.stage,
        preserved_empty.outcome,
        preserved_empty.reason_code,
        preserved_empty.source_length,
        preserved_empty.source_sha256,
        preserved_empty.duration_ms,
        preserved_empty.retry_count,
    ) == (
        "source_parse",
        ProcessingOutcome.AMBIGUOUS_EMPTY,
        "EMPTY_CELL",
        0,
        "e3b0c44298fc",
        2.5,
        1,
    )


@pytest.mark.asyncio
async def test_unexpected_exception_group_is_raised_after_best_effort_completion():
    dates = ["20260713", "20260714"]
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process.side_effect = [
        RuntimeError("<html>SECRET_TOKEN"),
        _parsed(dates[1]),
    ]
    notification_service = AsyncMock()
    service = SchedulingService(notification_service, scraping_service)

    with patch(
        "functions.shared.services.scheduling_service.emit_event", create=True
    ) as emit:
        with pytest.raises(ExceptionGroup) as raised:
            await service.process_weekly_schedule_general(
                RestaurantType.DODAM,
                dates,
                is_dev=False,
            )

    assert scraping_service.scrape_and_process.await_count == 2
    assert notification_service.send_date_summary.await_count == 2
    summaries = [call.args[0] for call in notification_service.send_date_summary.await_args_list]
    assert summaries[0].system_error is True
    assert summaries[1].system_error is False
    assert len(raised.value.exceptions) == 1
    wrapped = raised.value.exceptions[0]
    platform_trace = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert type(wrapped).__name__ == "SanitizedUnhandledError"
    assert wrapped.__cause__ is None
    assert wrapped.__context__ is None
    assert "<html>" not in platform_trace
    assert "SECRET_TOKEN" not in platform_trace
    event = next(call for call in emit.call_args_list if call.args[1] == "unhandled_exception")
    assert event.kwargs["error.type"] == "RuntimeError"
    assert event.kwargs["error.frames"]
    assert "SECRET_TOKEN" not in repr(event.kwargs)


@pytest.mark.asyncio
async def test_slack_final_failure_preserves_menu_outcome_and_surfaces_at_invocation_end():
    dates = ["20260713", "20260714"]
    parsed = [_parsed(date) for date in dates]
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process.side_effect = parsed
    notification_service = AsyncMock()
    notification_service.send_date_summary.side_effect = [
        SlackNotificationError("Slack notification failed"),
        True,
    ]
    service = SchedulingService(notification_service, scraping_service)

    with pytest.raises(ExceptionGroup) as raised:
        await service.process_weekly_schedule_general(
            RestaurantType.DODAM,
            dates,
            is_dev=False,
        )

    assert scraping_service.scrape_and_process.await_count == 2
    assert notification_service.send_date_summary.await_count == 2
    first_summary = notification_service.send_date_summary.await_args_list[0].args[0]
    assert first_summary.system_error is False
    assert first_summary.slot_results["중식1"].outcome is ProcessingOutcome.SUCCESS
    wrapped = raised.value.exceptions[0]
    platform_trace = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert type(wrapped).__name__ == "SanitizedUnhandledError"
    assert wrapped.__cause__ is None
    assert wrapped.__context__ is None
    assert "Slack notification failed" not in platform_trace


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_error", [RetryableEmptyMenuError, RetryableApiSendError])
async def test_dormitory_retryable_attempt_propagates_without_slack(retry_error):
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process_dormitory.side_effect = retry_error(
        "20260713",
        RestaurantType.DORMITORY,
    )
    notification_service = AsyncMock()
    service = SchedulingService(notification_service, scraping_service)

    with pytest.raises(retry_error):
        await service.process_weekly_schedule_dormitory(["20260713"], is_dev=False)

    notification_service.send_date_summary.assert_not_awaited()
    notification_service.send_menu_notification.assert_not_awaited()
    notification_service.send_error_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_slot_results_survive_parser_and_parser_wins_same_slot():
    source_closed = _slot(
        "석식1",
        ProcessingOutcome.EXPECTED_EMPTY,
        "CLOSED_MARKER",
        "source_fetch",
    )
    source_lunch = _slot("중식1", reason_code="SOURCE_SUCCESS", stage="source_fetch")
    parser_lunch = _slot("중식1", reason_code="PARSE_SUCCESS", stage="parse")
    raw = RawMenuData(
        "20260713",
        RestaurantType.DODAM,
        {"중식1": "밥"},
        {"중식1": source_lunch, "석식1": source_closed},
    )
    parser = MagicMock()
    parser.parse_menu = AsyncMock(
        return_value=ParsedMenuData(
            raw.date,
            raw.restaurant,
            {"중식1": ["밥"]},
            slot_results={"중식1": parser_lunch},
        )
    )
    service = ScrapingService(parser, AsyncMock(), AsyncMock(), MagicMock())

    parsed = await service._parse_menu(raw)

    assert parsed.slot_results["중식1"] is parser_lunch
    assert parsed.slot_results["석식1"] is source_closed
    assert "석식1" not in parsed.menus


@pytest.mark.asyncio
async def test_production_api_result_overrides_parser_and_ignores_dev_failure():
    parsed = _parsed("20260713")
    parsed.slot_results["중식1"] = SlotProcessingResult(
        slot="중식1",
        stage="parse",
        outcome=ProcessingOutcome.SUCCESS,
        reason_code="PARSE_SUCCESS",
        source_length=18,
        source_sha256="abc123def456",
        duration_ms=4.75,
        retry_count=1,
    )
    dev_client = AsyncMock()
    dev_client.post_menu.side_effect = MenuPostException(
        parsed.date,
        parsed.restaurant,
        None,
    )
    prod_client = AsyncMock()
    prod_client.post_menu.return_value = True
    service = ScrapingService(AsyncMock(), prod_client, dev_client, MagicMock())

    with patch.object(service, "_extract_time_slot", return_value=TimeSlot.LUNCH):
        await service.send_to_api(parsed, is_dev=False)

    result = parsed.slot_results["중식1"]
    assert result.stage == "menu_post"
    assert result.outcome is ProcessingOutcome.SUCCESS
    assert result.reason_code == "POST_SUCCESS"
    assert result.source_length == 18
    assert result.source_sha256 == "abc123def456"
    assert result.duration_ms == 4.75
    assert result.retry_count == 1
    assert parsed.error_slots == {}


@pytest.mark.asyncio
async def test_critical_api_failure_sets_slot_result_before_raising():
    parsed = _parsed("20260713")
    critical_client = AsyncMock()
    critical_client.post_menu.side_effect = MenuPostException(
        parsed.date,
        parsed.restaurant,
        None,
    )
    service = ScrapingService(AsyncMock(), AsyncMock(), critical_client, MagicMock())

    with patch.object(service, "_extract_time_slot", return_value=TimeSlot.LUNCH):
        with pytest.raises(MenuPostException):
            await service.send_to_api(parsed, is_dev=True)

    result = parsed.slot_results["중식1"]
    assert result.stage == "menu_post"
    assert result.outcome is ProcessingOutcome.API_FAILURE
    assert result.reason_code == "POST_ERROR"
    assert result.error_type == "MenuPostException"
