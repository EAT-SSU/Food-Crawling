import asyncio
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Mapping, NoReturn, Optional

from functions.shared.models.exceptions import (
    BaseRestaurantException,
    HolidayException,
    MenuFetchException,
    MenuParseException,
    MenuPostException,
    WeirdRestaurantNameException,
)
from functions.shared.models.model import (
    DateProcessingSummary,
    ParsedMenuData,
    ResponseBuilder,
    RestaurantType,
)
from functions.shared.observability import (
    SanitizedUnhandledError,
    bind_observation_context,
    build_run_id,
    emit_event,
    reset_observation_context,
    sanitize_exception,
)
from functions.shared.utils.date_utils import (
    WeekType,
    get_current_weekdays,
    get_next_weekdays,
)


_DATE_PATTERN = re.compile(r"\d{8}")
_TRIGGERS = {"direct", "eventbridge", "iam", "local", "step_functions"}
KNOWN_DOMAIN_ERRORS = (
    HolidayException,
    MenuFetchException,
    MenuParseException,
    MenuPostException,
    WeirdRestaurantNameException,
)


@dataclass
class HandlerEvent:
    trigger: str
    delayed_schedule: bool
    execution_id: Optional[str]
    retry_count: int
    target_date: Optional[str]
    sanitized_failure: Optional[SanitizedUnhandledError] = None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.lower() == "true"


def _date(value: object) -> Optional[str]:
    return value if isinstance(value, str) and _DATE_PATTERN.fullmatch(value) else None


def _retry_count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, str)):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def parse_handler_event(event: object) -> HandlerEvent:
    payload = _mapping(event)
    query = _mapping(payload.get("queryStringParameters"))
    raw_trigger = payload.get("trigger")
    trigger = raw_trigger if isinstance(raw_trigger, str) and raw_trigger in _TRIGGERS else "direct"
    delayed_value = (
        payload["delayed_schedule"]
        if "delayed_schedule" in payload
        else query.get("delayed_schedule")
    )
    execution_id = payload.get("execution_id")
    return HandlerEvent(
        trigger=trigger,
        delayed_schedule=_boolean(delayed_value),
        execution_id=execution_id if isinstance(execution_id, str) and execution_id else None,
        retry_count=_retry_count(payload.get("retry_count", 0)),
        target_date=_date(
            payload.get("target_date")
            or payload.get("date")
            or query.get("date")
        ),
    )


@contextmanager
def handler_observation(
    event: object,
    context,
    restaurant: RestaurantType,
    handler_kind: str,
) -> Iterator[HandlerEvent]:
    payload = _mapping(event)
    parsed = parse_handler_event(payload)
    tokens = bind_observation_context(
        service_name=f"food-crawling-{handler_kind}",
        invocation_id=context.aws_request_id,
        run_id=build_run_id(payload, context),
        restaurant=restaurant.english_name,
        trigger=parsed.trigger,
    )
    try:
        emit_event(
            "INFO",
            "handler_invocation_started",
            "handler",
            retry_count=parsed.retry_count,
            date=parsed.target_date,
        )
        yield parsed
        emit_event(
            "INFO",
            "handler_invocation_completed",
            "handler",
            retry_count=parsed.retry_count,
            date=parsed.target_date,
        )
    except BaseRestaurantException as error:
        safe_error = sanitize_exception(error)
        emit_event(
            "ERROR",
            "handler_invocation_failed",
            "handler",
            retry_count=parsed.retry_count,
            date=parsed.target_date,
            **{
                "error.type": safe_error["type"],
                "error.frames": safe_error.get("frames", []),
            },
        )
        raise
    except Exception as error:
        safe_error = sanitize_exception(error)
        emit_event(
            "ERROR",
            "handler_invocation_failed",
            "handler",
            retry_count=parsed.retry_count,
            date=parsed.target_date,
            **{
                "error.type": safe_error["type"],
                "error.frames": safe_error.get("frames", []),
            },
        )
        parsed.sanitized_failure = SanitizedUnhandledError()
    finally:
        reset_observation_context(tokens)


def raise_sanitized_handler_failure(request: HandlerEvent) -> NoReturn:
    failure = request.sanitized_failure or SanitizedUnhandledError()
    raise failure from None


def _success_response(results: list[ParsedMenuData]) -> dict[str, object]:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps([result.to_dict() for result in results], ensure_ascii=False),
    }


def _summary_from_parsed(parsed_menu: ParsedMenuData) -> DateProcessingSummary:
    return DateProcessingSummary(
        date=parsed_menu.date,
        restaurant=parsed_menu.restaurant,
        menus=parsed_menu.menus,
        slot_results=dict(parsed_menu.slot_results),
    )


def _summary_from_domain_error(
    error: Exception,
    date: str,
    restaurant: RestaurantType,
) -> DateProcessingSummary:
    from functions.shared.services.scheduling_service import SchedulingService

    return SchedulingService._summary_from_domain_error(error, date, restaurant)


def run_general_schedule_handler(
    event: object,
    context,
    restaurant: RestaurantType,
    week_type: WeekType,
) -> dict[str, object]:
    with handler_observation(event, context, restaurant, "scheduling") as request:
        if request.target_date:
            weekdays = [request.target_date]
        elif request.delayed_schedule:
            weekdays = get_current_weekdays(week_type=week_type)
        else:
            weekdays = get_next_weekdays(week_type=week_type)

        from functions.config.dependencies import get_container

        scheduling_service = get_container().get_scheduling_service()
        results = asyncio.run(
            scheduling_service.process_weekly_schedule_general(
                restaurant,
                weekdays,
                is_dev=False,
            )
        )
        return _success_response(results)
    raise_sanitized_handler_failure(request)


def run_dormitory_schedule_handler(event: object, context) -> dict[str, object]:
    restaurant = RestaurantType.DORMITORY
    with handler_observation(event, context, restaurant, "scheduling") as request:
        weekdays = (
            [request.target_date]
            if request.target_date
            else get_current_weekdays(week_type=WeekType.FULL_WEEK)
        )
        from functions.config.dependencies import get_container
        from functions.shared.models.exceptions import RetryableEmptyMenuError

        scheduling_service = get_container().get_scheduling_service()
        results = asyncio.run(
            scheduling_service.process_weekly_schedule_dormitory(
                weekdays,
                is_dev=False,
            )
        )
        if not results:
            raise RetryableEmptyMenuError(weekdays[0], restaurant)
        return _success_response(results)
    raise_sanitized_handler_failure(request)


def run_single_scraping_handler(
    event: object,
    context,
    restaurant: RestaurantType,
    *,
    special_note: Optional[str] = None,
) -> dict[str, object]:
    with handler_observation(event, context, restaurant, "scraping") as request:
        date = request.target_date or get_current_weekdays(WeekType.FULL_WEEK)[0]
        from functions.config.dependencies import get_container

        container = get_container()
        scraping_service = container.get_scraping_service()
        notification_service = container.get_notification_service()
        try:
            parsed_menu = asyncio.run(
                scraping_service.scrape_and_process(date, restaurant)
            )
        except KNOWN_DOMAIN_ERRORS as error:
            summary = _summary_from_domain_error(error, date, restaurant)
            asyncio.run(notification_service.send_date_summary(summary))
            return ResponseBuilder.create_error_response(
                date=date,
                restaurant=restaurant,
                error=error,
                status_code=400,
            )

        asyncio.run(notification_service.send_date_summary(_summary_from_parsed(parsed_menu)))
        return ResponseBuilder.create_success_response(
            parsed_menu,
            message=f"{restaurant.korean_name} 메뉴 처리 완료",
            special_note=special_note,
        )
    raise_sanitized_handler_failure(request)


def run_dormitory_scraping_handler(event: object, context) -> dict[str, object]:
    restaurant = RestaurantType.DORMITORY
    with handler_observation(event, context, restaurant, "scraping") as request:
        date = request.target_date or get_current_weekdays(WeekType.FULL_WEEK)[0]
        from functions.config.dependencies import get_container

        container = get_container()
        scraping_service = container.get_scraping_service()
        notification_service = container.get_notification_service()
        try:
            parsed_menus = asyncio.run(
                scraping_service.scrape_and_process_dormitory(date)
            )
        except KNOWN_DOMAIN_ERRORS as error:
            summary = _summary_from_domain_error(error, date, restaurant)
            asyncio.run(notification_service.send_date_summary(summary))
            return ResponseBuilder.create_error_response(
                date=date,
                restaurant=restaurant,
                error=error,
                status_code=400,
            )

        for parsed_menu in parsed_menus:
            asyncio.run(
                notification_service.send_date_summary(
                    _summary_from_parsed(parsed_menu)
                )
            )

        combined_menus = {
            f"{parsed_menu.date}_{slot}": items
            for parsed_menu in parsed_menus
            for slot, items in parsed_menu.menus.items()
        }
        combined_errors = {
            f"{parsed_menu.date}_{slot}": error
            for parsed_menu in parsed_menus
            for slot, error in parsed_menu.error_slots.items()
        }
        combined_results = {
            f"{parsed_menu.date}_{slot}": result
            for parsed_menu in parsed_menus
            for slot, result in parsed_menu.slot_results.items()
        }
        combined = ParsedMenuData(
            date=f"{date}_weekly",
            restaurant=restaurant,
            menus=combined_menus,
            error_slots=combined_errors,
            success=not combined_errors,
            slot_results=combined_results,
        )
        return ResponseBuilder.create_success_response(
            combined,
            message=f"{restaurant.korean_name} 주간 메뉴 처리 완료 ({len(parsed_menus)}일치)",
            special_note="기숙사식당은 조식을 운영하지 않습니다",
        )
    raise_sanitized_handler_failure(request)
