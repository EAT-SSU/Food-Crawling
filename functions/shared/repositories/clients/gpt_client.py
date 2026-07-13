import contextvars
import json
import re
import time
from typing import Any, Optional, Tuple, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionToolParam
from tenacity import RetryCallState, retry, stop_after_attempt, wait_fixed

from functions.config.settings import Settings
from functions.shared.models.exceptions import MenuParseException
from functions.shared.models.model import (
    ParsedMenuData,
    ProcessingOutcome,
    RawMenuData,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import emit_event, fingerprint_source, measure_duration
from functions.shared.repositories.interfaces import MenuParserInterface


_attempt_number: contextvars.ContextVar[int] = contextvars.ContextVar(
    "gpt_attempt_number", default=0
)
_attempt_started_ns: contextvars.ContextVar[int] = contextvars.ContextVar(
    "gpt_attempt_started_ns", default=0
)


def _before_attempt(retry_state: RetryCallState) -> None:
    _attempt_number.set(retry_state.attempt_number - 1)
    _attempt_started_ns.set(time.perf_counter_ns())


def _before_sleep(retry_state: RetryCallState) -> None:
    _, target_date, restaurant, slot, source = _call_arguments(retry_state)
    source_length, source_sha256 = fingerprint_source(source)
    error = retry_state.outcome.exception() if retry_state.outcome else None
    emit_event(
        "WARNING",
        "client.retry",
        "parse",
        date=target_date,
        restaurant=restaurant.english_name,
        slot=slot,
        status="retrying",
        retry_count=retry_state.attempt_number,
        duration_ms=measure_duration(_attempt_started_ns.get()),
        source_length=source_length,
        source_sha256=source_sha256,
        **{"error.type": type(error).__name__ if error else "UnknownError"},
    )


def _call_arguments(
    retry_state: RetryCallState,
) -> tuple[object, str, RestaurantType, str, str]:
    args = retry_state.args
    kwargs = retry_state.kwargs
    return (
        args[0],
        cast(str, args[1] if len(args) > 1 else kwargs["target_date"]),
        cast(RestaurantType, args[2] if len(args) > 2 else kwargs["restaurant"]),
        cast(str, args[3] if len(args) > 3 else kwargs["slot"]),
        cast(str, args[4] if len(args) > 4 else kwargs["source"]),
    )


class GPTClient(MenuParserInterface):
    """OpenAI GPT API client with isolated retries for each menu slot."""

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        function_tools: Optional[list[ChatCompletionToolParam]] = None,
        system_prompt: Optional[str] = None,
    ):
        self.client = AsyncOpenAI(api_key=api_key)

        settings: Optional[Settings] = None
        if model is None or function_tools is None or system_prompt is None:
            from functions.config.settings import get_settings

            settings = get_settings()

        if model is None:
            assert settings is not None
            model = settings.GPT_MODEL
        if function_tools is None:
            assert settings is not None
            function_tools = cast(
                list[ChatCompletionToolParam], settings.GPT_FUNCTION_TOOLS
            )
        if system_prompt is None:
            assert settings is not None
            system_prompt = settings.GPT_SYSTEM_PROMPT

        self.model = model
        self.function_tools = function_tools
        self.system_prompt = system_prompt

    async def parse_menu(self, raw_menu: RawMenuData) -> ParsedMenuData:
        result_dict = {}
        errors = {}
        slot_results = {}

        for slot, source in raw_menu.menu_texts.items():
            source_length, source_sha256 = fingerprint_source(source)
            if not source.strip():
                result_dict[slot] = []
                error = MenuParseException(
                    raw_menu.date,
                    raw_menu.restaurant,
                    reason_code="PARSE_EMPTY",
                )
                errors[slot] = error
                slot_results[slot] = SlotProcessingResult(
                    slot=slot,
                    stage="parse",
                    outcome=ProcessingOutcome.AMBIGUOUS_EMPTY,
                    reason_code="EMPTY_SOURCE",
                    source_length=source_length,
                    source_sha256=source_sha256,
                    duration_ms=0.0,
                    retry_count=0,
                    error_type=type(error).__name__,
                )
                emit_event(
                    "WARNING",
                    "client.completed",
                    "parse",
                    date=raw_menu.date,
                    restaurant=raw_menu.restaurant.english_name,
                    slot=slot,
                    status="empty",
                    outcome=ProcessingOutcome.AMBIGUOUS_EMPTY,
                    reason_code="EMPTY_SOURCE",
                    retry_count=0,
                    duration_ms=0.0,
                    source_length=source_length,
                    source_sha256=source_sha256,
                    model=self.model,
                    **{"error.type": type(error).__name__},
                )
                continue

            try:
                menus, _, retry_count, duration_ms = await self._parse_slot(
                    raw_menu.date, raw_menu.restaurant, slot, source
                )
            except Exception as provider_error:
                error = MenuParseException(
                    raw_menu.date,
                    raw_menu.restaurant,
                    reason_code="PARSE_ERROR",
                )
                result_dict[slot] = []
                errors[slot] = error
                slot_results[slot] = SlotProcessingResult(
                    slot=slot,
                    stage="parse",
                    outcome=ProcessingOutcome.PARSER_FAILURE,
                    reason_code="PARSE_ERROR",
                    source_length=source_length,
                    source_sha256=source_sha256,
                    duration_ms=measure_duration(_attempt_started_ns.get()),
                    retry_count=2,
                    error_type=type(provider_error).__name__,
                )
                emit_event(
                    "ERROR",
                    "client.completed",
                    "parse",
                    date=raw_menu.date,
                    restaurant=raw_menu.restaurant.english_name,
                    slot=slot,
                    status="failure",
                    outcome=ProcessingOutcome.PARSER_FAILURE,
                    reason_code="PARSE_ERROR",
                    retry_count=2,
                    duration_ms=measure_duration(_attempt_started_ns.get()),
                    source_length=source_length,
                    source_sha256=source_sha256,
                    model=self.model,
                    **{"error.type": type(provider_error).__name__},
                )
                continue

            result_dict[slot] = menus
            if menus:
                slot_results[slot] = SlotProcessingResult(
                    slot=slot,
                    stage="parse",
                    outcome=ProcessingOutcome.SUCCESS,
                    reason_code="PARSE_SUCCESS",
                    source_length=source_length,
                    source_sha256=source_sha256,
                    duration_ms=duration_ms,
                    retry_count=retry_count,
                )
            else:
                error = MenuParseException(
                    raw_menu.date,
                    raw_menu.restaurant,
                    reason_code="PARSE_EMPTY",
                )
                errors[slot] = error
                slot_results[slot] = SlotProcessingResult(
                    slot=slot,
                    stage="parse",
                    outcome=ProcessingOutcome.PARSER_FAILURE,
                    reason_code="PARSE_EMPTY",
                    source_length=source_length,
                    source_sha256=source_sha256,
                    duration_ms=duration_ms,
                    retry_count=retry_count,
                    error_type=type(error).__name__,
                )

        return ParsedMenuData(
            date=raw_menu.date,
            restaurant=raw_menu.restaurant,
            menus=result_dict,
            error_slots=errors,
            success=not errors,
            slot_results=slot_results,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=_before_attempt,
        before_sleep=_before_sleep,
    )
    async def _parse_slot(
        self,
        target_date: str,
        restaurant: RestaurantType,
        slot: str,
        source: str,
    ) -> Tuple[list[str], Optional[str], int, float]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": f"다음 식당 메뉴 텍스트에서 실제 음식 메뉴만 추출해주세요:\n\n{Settings.FACULTY_EXAMPLE_RAW_MENU}",
                },
                {
                    "role": "assistant",
                    "content": f"{Settings.FACULTY_EXAMPLE_PARSED_MENU}",
                },
                {
                    "role": "user",
                    "content": f"다음 식당 메뉴 텍스트에서 실제 음식 메뉴만 추출해주세요:\n\n{source}",
                },
            ],
            tools=self.function_tools,
            tool_choice={"type": "function", "function": {"name": "extract_all_menus"}},
        )

        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            raise ValueError("Malformed provider response")
        tool_call = tool_calls[0]
        function_args = json.loads(tool_call.function.arguments)
        if not isinstance(function_args, dict):
            raise ValueError("Malformed provider response")
        raw_menus: Any = function_args.get("all_menus", [])
        if not isinstance(raw_menus, list) or not all(
            isinstance(menu, str) for menu in raw_menus
        ):
            raise ValueError("Malformed provider response")
        menus = cast(list[str], raw_menus)
        refined_menus = [re.sub(r"[\*]+(?=[가-힣])", "", menu) for menu in menus]
        retry_count = _attempt_number.get()
        duration_ms = measure_duration(_attempt_started_ns.get())
        request_id = getattr(response, "id", None)
        safe_request_id = request_id if isinstance(request_id, str) else None
        source_length, source_sha256 = fingerprint_source(source)
        outcome = (
            ProcessingOutcome.SUCCESS
            if refined_menus
            else ProcessingOutcome.PARSER_FAILURE
        )
        reason_code = "PARSE_SUCCESS" if refined_menus else "PARSE_EMPTY"
        emit_event(
            "INFO" if refined_menus else "WARNING",
            "client.completed",
            "parse",
            date=target_date,
            restaurant=restaurant.english_name,
            slot=slot,
            status="success" if refined_menus else "empty",
            outcome=outcome,
            reason_code=reason_code,
            retry_count=retry_count,
            duration_ms=duration_ms,
            source_length=source_length,
            source_sha256=source_sha256,
            model=self.model,
            provider_request_id=safe_request_id,
        )
        return refined_menus, safe_request_id, retry_count, duration_ms
