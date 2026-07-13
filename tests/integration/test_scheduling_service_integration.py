from unittest.mock import AsyncMock

import pytest

from functions.shared.models.model import (
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.services.scheduling_service import SchedulingService


def _parsed(date: str) -> ParsedMenuData:
    return ParsedMenuData(
        date=date,
        restaurant=RestaurantType.HAKSIK,
        menus={"중식1": ["밥", "국"]},
        slot_results={
            "중식1": SlotProcessingResult(
                slot="중식1",
                stage="menu_post",
                outcome=ProcessingOutcome.SUCCESS,
                reason_code="POST_SUCCESS",
            )
        },
    )


@pytest.mark.asyncio
async def test_general_schedule_uses_current_async_service_contract():
    weekdays = ["20260713", "20260714", "20260715"]
    parsed = [_parsed(date) for date in weekdays]
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process.side_effect = parsed
    notification_service = AsyncMock()
    service = SchedulingService(notification_service, scraping_service)

    result = await service.process_weekly_schedule_general(
        RestaurantType.HAKSIK,
        weekdays,
        is_dev=False,
    )

    assert result == parsed
    assert scraping_service.scrape_and_process.await_count == len(weekdays)
    assert [call.args[0] for call in scraping_service.scrape_and_process.await_args_list] == weekdays
    assert notification_service.send_date_summary.await_count == len(weekdays)
    assert [
        call.args[0].date for call in notification_service.send_date_summary.await_args_list
    ] == weekdays
    notification_service.send_menu_notification.assert_not_awaited()
    notification_service.send_error_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_dormitory_success_sends_one_summary_per_returned_date():
    parsed = [_parsed("20260713"), _parsed("20260714")]
    for menu in parsed:
        menu.restaurant = RestaurantType.DORMITORY
    scraping_service = AsyncMock()
    scraping_service.scrape_and_process_dormitory.return_value = parsed
    notification_service = AsyncMock()
    service = SchedulingService(notification_service, scraping_service)

    result = await service.process_weekly_schedule_dormitory(
        ["20260713", "20260714"],
        is_dev=False,
    )

    assert result == parsed
    assert notification_service.send_date_summary.await_count == 2
    assert [
        call.args[0].date for call in notification_service.send_date_summary.await_args_list
    ] == ["20260713", "20260714"]
    notification_service.send_menu_notification.assert_not_awaited()
    notification_service.send_error_notification.assert_not_awaited()
