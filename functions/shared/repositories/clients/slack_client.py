import contextvars
import re
import time
from typing import Optional, Union, cast

import aiohttp
from tenacity import RetryCallState, retry, stop_after_attempt, wait_fixed

from functions.shared.models.model import (
    DateProcessingSummary,
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import emit_event, measure_duration


_SLOT_FAMILY_ORDER = ["조식", "중식", "석식"]

_API_FAILURE_STAGE_WORDING: dict[str, str] = {
    "source_fetch": "메뉴 원본 조회 실패",
    "menu_post": "메뉴 저장 실패",
}
_API_FAILURE_FALLBACK = "외부 연동 실패"
_DATE_PATTERN = re.compile(r"\d{8}")


def _slot_sort_key(slot: str) -> tuple[int, float]:
    for i, family in enumerate(_SLOT_FAMILY_ORDER):
        if slot.startswith(family):
            suffix = slot[len(family):]
            numeric: float = int(suffix) if suffix.isdigit() else float("inf")
            return (i, numeric)
    return (len(_SLOT_FAMILY_ORDER), float("inf"))


SafeStatus = Union[int, str]
_attempt_number: contextvars.ContextVar[int] = contextvars.ContextVar(
    "slack_attempt_number", default=0
)
_attempt_started_ns: contextvars.ContextVar[int] = contextvars.ContextVar(
    "slack_attempt_started_ns", default=0
)


class SlackNotificationError(RuntimeError):
    """Fixed-message notification failure safe for propagation."""


def _safe_status(value: object) -> SafeStatus:
    return value if isinstance(value, int) else "unknown"


def _exception_status(error: BaseException) -> SafeStatus:
    return _safe_status(getattr(error, "_safe_status", None))


def _before_attempt(retry_state: RetryCallState) -> None:
    _attempt_number.set(retry_state.attempt_number - 1)
    _attempt_started_ns.set(time.perf_counter_ns())


def _message_argument(retry_state: RetryCallState) -> str:
    args = retry_state.args
    return cast(str, args[1] if len(args) > 1 else retry_state.kwargs["message"])


def _event_fields(retry_state: RetryCallState) -> dict[str, object]:
    message = _message_argument(retry_state)
    outcome = retry_state.outcome
    error = outcome.exception() if outcome is not None else None
    return {
        "status": _exception_status(error) if error else "unknown",
        "duration_ms": measure_duration(_attempt_started_ns.get()),
        "message_length": len(message),
        "error.type": type(error).__name__ if error else "UnknownError",
    }


def _before_sleep(retry_state: RetryCallState) -> None:
    emit_event(
        "WARNING",
        "client.retry",
        "slack_notify",
        retry_count=retry_state.attempt_number,
        **_event_fields(retry_state),
    )


def _after_attempt(retry_state: RetryCallState) -> None:
    outcome = retry_state.outcome
    if retry_state.attempt_number != 3 or outcome is None or not outcome.failed:
        return
    emit_event(
        "ERROR",
        "client.completed",
        "slack_notify",
        outcome=ProcessingOutcome.API_FAILURE,
        reason_code="SLACK_ERROR",
        retry_count=2,
        **_event_fields(retry_state),
    )


class SlackClient:
    """Slack notification client."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def build_date_summary_message(self, summary: DateProcessingSummary) -> str:
        header = f"🍽️ {summary.restaurant.korean_name}({summary.date})"
        lines = [header]

        if summary.system_error:
            lines.append("⚠️ 처리 중 시스템 오류")
            return "\n".join(lines)

        if (
            summary.date_outcome is ProcessingOutcome.EXPECTED_EMPTY
            and summary.reason_code == "HOLIDAY"
            and not summary.slot_results
        ):
            lines.append("ℹ️ 휴무일")
            return "\n".join(lines)

        sorted_slots = sorted(summary.slot_results.keys(), key=_slot_sort_key)

        for slot in sorted_slots:
            result = summary.slot_results[slot]
            outcome = result.outcome

            if outcome is ProcessingOutcome.SUCCESS:
                menus = summary.menus.get(slot, [])
                lines.append(f"✅ {slot}: {', '.join(menus)}")
            elif outcome is ProcessingOutcome.EXPECTED_EMPTY:
                lines.append(f"ℹ️ {slot}: 휴무/미운영")
            elif outcome is ProcessingOutcome.AMBIGUOUS_EMPTY:
                lines.append(f"⚠️ {slot}: 메뉴 미게시 여부 확인 필요")
            elif outcome is ProcessingOutcome.PARSER_FAILURE:
                lines.append(f"⚠️ {slot}: 메뉴 파싱 실패")
            elif outcome is ProcessingOutcome.API_FAILURE:
                wording = _API_FAILURE_STAGE_WORDING.get(result.stage, _API_FAILURE_FALLBACK)
                lines.append(f"⚠️ {slot}: {wording}")

        return "\n".join(lines)

    async def send_date_summary(self, summary: DateProcessingSummary) -> bool:
        message = self.build_date_summary_message(summary)
        return await self._send_message(message)

    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        slot_results = dict(parsed_menu.slot_results)
        for slot, menus in parsed_menu.menus.items():
            if slot in slot_results:
                continue
            if slot in parsed_menu.error_slots:
                outcome = ProcessingOutcome.PARSER_FAILURE
                reason_code = "PARSE_ERROR"
            elif menus:
                outcome = ProcessingOutcome.SUCCESS
                reason_code = "LEGACY_SUCCESS"
            else:
                outcome = ProcessingOutcome.AMBIGUOUS_EMPTY
                reason_code = "SOURCE_EMPTY"
            slot_results[slot] = SlotProcessingResult(
                slot=slot,
                stage="parse",
                outcome=outcome,
                reason_code=reason_code,
            )
        for slot in parsed_menu.error_slots:
            slot_results.setdefault(
                slot,
                SlotProcessingResult(
                    slot=slot,
                    stage="parse",
                    outcome=ProcessingOutcome.PARSER_FAILURE,
                    reason_code="PARSE_ERROR",
                ),
            )
        return await self.send_date_summary(
            DateProcessingSummary(
                date=parsed_menu.date,
                restaurant=parsed_menu.restaurant,
                menus=parsed_menu.menus,
                slot_results=slot_results,
            )
        )

    async def send_error_notification(
        self,
        exception: Exception,
        date: Optional[str] = None,
        restaurant_type: Optional[RestaurantType] = None,
    ) -> bool:
        if date and _DATE_PATTERN.fullmatch(date) and restaurant_type:
            return await self.send_date_summary(
                DateProcessingSummary(
                    date=date,
                    restaurant=restaurant_type,
                    menus={},
                    slot_results={},
                    system_error=True,
                )
            )
        return await self._send_message("⚠️ 처리 중 시스템 오류")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        reraise=True,
        before=_before_attempt,
        before_sleep=_before_sleep,
        after=_after_attempt,
    )
    async def _send_message(self, message: str) -> bool:
        payload = {
            "username": "학식봇",
            "text": message,
            "icon_emoji": ":fork_and_knife:",
        }
        status: SafeStatus = "unknown"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    status = _safe_status(response.status)
                    response.raise_for_status()
        except Exception:
            error = SlackNotificationError("Slack notification failed")
            setattr(error, "_safe_status", status)
            raise error from None

        emit_event(
            "INFO",
            "client.completed",
            "slack_notify",
            status=status,
            duration_ms=measure_duration(_attempt_started_ns.get()),
            message_length=len(message),
            retry_count=_attempt_number.get(),
            outcome=ProcessingOutcome.SUCCESS,
            reason_code="SLACK_SUCCESS",
        )
        return True
