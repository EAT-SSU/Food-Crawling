from typing import List

from functions.shared.models.exceptions import (
    HolidayException,
    MenuFetchException,
    MenuParseException,
    MenuPostException,
    WeirdRestaurantNameException,
)
from functions.shared.models.model import (
    DateProcessingSummary,
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import (
    SanitizedUnhandledError,
    emit_event,
    sanitize_exception,
)


_KNOWN_DOMAIN_ERRORS = (
    HolidayException,
    MenuFetchException,
    MenuParseException,
    MenuPostException,
    WeirdRestaurantNameException,
)


class SchedulingService:
    """Coordinate weekly processing while preserving per-date outcomes."""

    def __init__(self, notification_service, scraping_service):
        self.notification_service = notification_service
        self.scraping_service = scraping_service

    async def process_weekly_schedule_general(
        self,
        restaurant_type: RestaurantType,
        weekdays: List[str],
        is_dev: bool,
    ) -> List[ParsedMenuData]:
        parsed_menus: List[ParsedMenuData] = []
        unexpected_failures: list[SanitizedUnhandledError] = []

        emit_event(
            "INFO",
            "weekly_processing_started",
            "scheduling",
            restaurant=restaurant_type.english_name,
            date_count=len(weekdays),
        )

        for date in weekdays:
            emit_event(
                "INFO",
                "date_processing_started",
                "scheduling",
                restaurant=restaurant_type.english_name,
                date=date,
            )
            try:
                parsed_menu = await self.scraping_service.scrape_and_process(
                    date,
                    restaurant_type,
                    is_dev=is_dev,
                )
                parsed_menus.append(parsed_menu)
                summary = self._summary_from_parsed(parsed_menu)
            except _KNOWN_DOMAIN_ERRORS as error:
                summary = self._summary_from_domain_error(
                    error,
                    date,
                    restaurant_type,
                )
            except Exception as error:
                self._emit_unhandled(error, date, restaurant_type, "scheduling")
                unexpected_failures.append(SanitizedUnhandledError())
                summary = DateProcessingSummary(
                    date=date,
                    restaurant=restaurant_type,
                    menus={},
                    slot_results={},
                    system_error=True,
                )

            try:
                await self.notification_service.send_date_summary(summary)
            except Exception as error:
                self._emit_unhandled(error, date, restaurant_type, "slack_notify")
                unexpected_failures.append(SanitizedUnhandledError())

            emit_event(
                "INFO",
                "date_processing_completed",
                "scheduling",
                restaurant=restaurant_type.english_name,
                date=date,
                system_error=summary.system_error,
                outcome=summary.date_outcome,
                reason_code=summary.reason_code,
            )

        emit_event(
            "INFO" if not unexpected_failures else "ERROR",
            "weekly_processing_completed",
            "scheduling",
            restaurant=restaurant_type.english_name,
            date_count=len(weekdays),
            parsed_count=len(parsed_menus),
            unexpected_failure_count=len(unexpected_failures),
        )
        if unexpected_failures:
            raise ExceptionGroup(
                "Unexpected weekly scheduling failures",
                unexpected_failures,
            )
        return parsed_menus

    async def process_weekly_schedule_dormitory(
        self,
        weekdays: List[str],
        is_dev: bool,
    ) -> List[ParsedMenuData]:
        restaurant_type = RestaurantType.DORMITORY
        date = weekdays[0]
        emit_event(
            "INFO",
            "weekly_processing_started",
            "scheduling",
            restaurant=restaurant_type.english_name,
            date=date,
        )

        parsed_menus = await self.scraping_service.scrape_and_process_dormitory(
            date,
            is_dev=is_dev,
        )

        notification_failures: list[SanitizedUnhandledError] = []
        for parsed_menu in parsed_menus:
            summary = self._summary_from_parsed(parsed_menu)
            try:
                await self.notification_service.send_date_summary(summary)
            except Exception as error:
                self._emit_unhandled(
                    error,
                    parsed_menu.date,
                    restaurant_type,
                    "slack_notify",
                )
                notification_failures.append(SanitizedUnhandledError())

        emit_event(
            "INFO" if not notification_failures else "ERROR",
            "weekly_processing_completed",
            "scheduling",
            restaurant=restaurant_type.english_name,
            date_count=len(parsed_menus),
            unexpected_failure_count=len(notification_failures),
        )
        if notification_failures:
            raise ExceptionGroup(
                "Unexpected dormitory notification failures",
                notification_failures,
            )
        return parsed_menus

    @staticmethod
    def _summary_from_parsed(parsed_menu: ParsedMenuData) -> DateProcessingSummary:
        return DateProcessingSummary(
            date=parsed_menu.date,
            restaurant=parsed_menu.restaurant,
            menus=parsed_menu.menus,
            slot_results=dict(parsed_menu.slot_results),
        )

    @staticmethod
    def _summary_from_domain_error(
        error: Exception,
        date: str,
        restaurant_type: RestaurantType,
    ) -> DateProcessingSummary:
        if isinstance(error, HolidayException):
            return DateProcessingSummary(
                date=date,
                restaurant=restaurant_type,
                menus={},
                slot_results={},
                date_outcome=ProcessingOutcome.EXPECTED_EMPTY,
                reason_code="HOLIDAY",
            )

        fallback: tuple[ProcessingOutcome, str, str]
        if isinstance(error, MenuFetchException):
            fallback = (
                ProcessingOutcome.AMBIGUOUS_EMPTY,
                "SOURCE_EMPTY",
                "source_fetch",
            )
        elif isinstance(error, MenuPostException):
            fallback = (ProcessingOutcome.API_FAILURE, "POST_ERROR", "menu_post")
        else:
            fallback = (ProcessingOutcome.PARSER_FAILURE, "PARSE_ERROR", "parse")

        raw_outcome = getattr(error, "outcome", None)
        try:
            outcome = (
                raw_outcome
                if isinstance(raw_outcome, ProcessingOutcome)
                else ProcessingOutcome(raw_outcome)
                if raw_outcome is not None
                else fallback[0]
            )
        except ValueError:
            outcome = fallback[0]
        reason_code = getattr(error, "reason_code", None) or fallback[1]
        stage = fallback[2]
        error_type = getattr(error, "error_type", None) or type(error).__name__

        raw_data = getattr(error, "raw_data", None)
        source_results = getattr(raw_data, "slot_results", {})
        if source_results:
            slot_results = {
                slot: SlotProcessingResult(
                    slot=result.slot,
                    stage=result.stage,
                    outcome=result.outcome,
                    reason_code=result.reason_code,
                    source_length=result.source_length,
                    source_sha256=result.source_sha256,
                    duration_ms=result.duration_ms,
                    retry_count=result.retry_count,
                    error_type=result.error_type or error_type,
                )
                for slot, result in source_results.items()
            }
        else:
            slot = "__source__" if stage == "source_fetch" else "__date__"
            slot_results = {
                slot: SlotProcessingResult(
                    slot=slot,
                    stage=stage,
                    outcome=outcome,
                    reason_code=reason_code,
                    error_type=error_type,
                )
            }

        return DateProcessingSummary(
            date=date,
            restaurant=restaurant_type,
            menus={},
            slot_results=slot_results,
            date_outcome=outcome,
            reason_code=reason_code,
        )

    @staticmethod
    def _emit_unhandled(
        error: Exception,
        date: str,
        restaurant_type: RestaurantType,
        stage: str,
    ) -> None:
        safe_error = sanitize_exception(error)
        emit_event(
            "ERROR",
            "unhandled_exception",
            stage,
            restaurant=restaurant_type.english_name,
            date=date,
            **{
                "error.type": safe_error["type"],
                "error.frames": safe_error.get("frames", []),
            },
        )
