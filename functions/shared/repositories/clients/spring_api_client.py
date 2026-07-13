import contextvars
import time
from dataclasses import asdict
from typing import Union, cast

import aiohttp
from tenacity import RetryCallState, retry, stop_after_attempt, wait_fixed

from functions.shared.models.exceptions import MenuPostException
from functions.shared.models.model import ProcessingOutcome, RequestBody, RestaurantType, TimeSlot
from functions.shared.observability import emit_event, measure_duration
from functions.shared.repositories.interfaces import APIClientInterface


SafeStatus = Union[int, str]
_attempt_number: contextvars.ContextVar[int] = contextvars.ContextVar(
    "spring_attempt_number", default=0
)
_attempt_started_ns: contextvars.ContextVar[int] = contextvars.ContextVar(
    "spring_attempt_started_ns", default=0
)


def _safe_status(value: object) -> SafeStatus:
    return value if isinstance(value, int) else "unknown"


def _exception_status(error: BaseException) -> SafeStatus:
    return _safe_status(getattr(error, "_safe_status", None))


def _before_attempt(retry_state: RetryCallState) -> None:
    _attempt_number.set(retry_state.attempt_number - 1)
    _attempt_started_ns.set(time.perf_counter_ns())


def _call_arguments(
    retry_state: RetryCallState,
) -> tuple["SpringAPIClient", str, RestaurantType, TimeSlot, list[str], int]:
    args = retry_state.args
    kwargs = retry_state.kwargs
    return (
        cast("SpringAPIClient", args[0]),
        cast(str, args[1] if len(args) > 1 else kwargs["date"]),
        cast(RestaurantType, args[2] if len(args) > 2 else kwargs["restaurant"]),
        cast(TimeSlot, args[3] if len(args) > 3 else kwargs["time_slot"]),
        cast(list[str], args[4] if len(args) > 4 else kwargs["menus"]),
        cast(int, args[5] if len(args) > 5 else kwargs["price"]),
    )


def _event_fields(retry_state: RetryCallState) -> dict[str, object]:
    client, date, restaurant, time_slot, menus, _ = _call_arguments(retry_state)
    outcome = retry_state.outcome
    error = outcome.exception() if outcome is not None else None
    return {
        "date": date,
        "restaurant": restaurant.english_name,
        "slot": time_slot.english_name,
        "environment": client.environment,
        "status": _exception_status(error) if error else "unknown",
        "duration_ms": measure_duration(_attempt_started_ns.get()),
        "menu_count": len(menus),
        "error.type": type(error).__name__ if error else "UnknownError",
    }


def _before_sleep(retry_state: RetryCallState) -> None:
    emit_event(
        "WARNING",
        "client.retry",
        "menu_post",
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
        "menu_post",
        outcome=ProcessingOutcome.API_FAILURE,
        reason_code="POST_ERROR",
        retry_count=2,
        **_event_fields(retry_state),
    )


class SpringAPIClient(APIClientInterface):
    """Spring Boot API client."""

    def __init__(self, base_url: str, environment: str = "prod"):
        self.base_url = base_url
        self.environment = environment

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        reraise=True,
        before=_before_attempt,
        before_sleep=_before_sleep,
        after=_after_attempt,
    )
    async def post_menu(
        self,
        date: str,
        restaurant: RestaurantType,
        time_slot: TimeSlot,
        menus: list[str],
        price: int,
    ) -> bool:
        form_data = asdict(RequestBody(price=price, menuNames=menus))
        params = {
            "date": date,
            "restaurant": restaurant.english_name,
            "time": time_slot.english_name,
        }
        post_url = f"{self.base_url.rstrip('/')}/meals/with-price"
        status: SafeStatus = "unknown"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    post_url,
                    json=form_data,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    status = _safe_status(response.status)
                    response.raise_for_status()
        except Exception:
            error = MenuPostException(
                target_date=date,
                restaurant_type=restaurant,
                details=None,
            )
            setattr(error, "_safe_status", status)
            raise error from None

        emit_event(
            "INFO",
            "client.completed",
            "menu_post",
            date=date,
            restaurant=restaurant.english_name,
            slot=time_slot.english_name,
            environment=self.environment,
            status=status,
            duration_ms=measure_duration(_attempt_started_ns.get()),
            menu_count=len(menus),
            retry_count=_attempt_number.get(),
            outcome=ProcessingOutcome.SUCCESS,
            reason_code="POST_SUCCESS",
        )
        return True
