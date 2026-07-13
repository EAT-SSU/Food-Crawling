import contextvars
import hashlib
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Protocol, TextIO, Tuple


LOGGER_NAME = "food_crawling.observation"
_HANDLER_MARKER = "_food_crawling_observation_handler"

SAFE_EXCEPTION_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "RESTAURANT_ERROR": "메뉴 처리 실패",
        "HOLIDAY": "휴무일",
        "SOURCE_EMPTY": "메뉴 미게시 또는 원본 누락",
        "SOURCE_SCHEMA_CHANGED": "메뉴 원본 구조 변경",
        "SOURCE_HTTP_ERROR": "메뉴 원본 조회 실패",
        "PARSE_EMPTY": "메뉴 파싱 실패",
        "PARSE_ERROR": "메뉴 파싱 실패",
        "UNKNOWN_MEAL_TIME": "지원하지 않는 식사 시간",
        "POST_ERROR": "메뉴 저장 실패",
        "RETRYABLE_EMPTY": "메뉴 미게시로 재시도 필요",
        "RETRYABLE_API": "메뉴 저장 재시도 필요",
    }
)
_FALLBACK_EXCEPTION_REASON_CODE = "RESTAURANT_ERROR"

_service_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "observation_service_name", default="unknown"
)
_invocation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "observation_invocation_id", default="unknown"
)
_run_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "observation_run_id", default="unknown"
)
_restaurant: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "observation_restaurant", default=None
)
_trigger: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "observation_trigger", default=None
)


@dataclass(frozen=True)
class ObservationTokens:
    service_name: contextvars.Token[str]
    invocation_id: contextvars.Token[str]
    run_id: contextvars.Token[str]
    restaurant: contextvars.Token[Optional[str]]
    trigger: contextvars.Token[Optional[str]]


class LambdaContext(Protocol):
    aws_request_id: str


class SanitizedUnhandledError(RuntimeError):
    """Fixed platform failure that never retains the original exception."""

    def __init__(self) -> None:
        super().__init__("Unexpected internal error")


def initialize_observation_logger(stream: Optional[TextIO] = None) -> logging.Logger:
    """Configure the isolated observation logger without touching root logging."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = next(
        (
            existing
            for existing in logger.handlers
            if isinstance(existing, logging.StreamHandler)
            and getattr(existing, _HANDLER_MARKER, False)
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(stream or sys.stdout)
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    elif stream is not None:
        handler.stream = stream

    return logger


def bind_observation_context(
    service_name: str,
    invocation_id: str,
    run_id: str,
    restaurant: Optional[str] = None,
    trigger: Optional[str] = None,
) -> ObservationTokens:
    """Bind invocation correlation values and return resettable tokens."""
    return ObservationTokens(
        service_name=_service_name.set(service_name),
        invocation_id=_invocation_id.set(invocation_id),
        run_id=_run_id.set(run_id),
        restaurant=_restaurant.set(restaurant),
        trigger=_trigger.set(trigger),
    )


def reset_observation_context(tokens: ObservationTokens) -> None:
    """Restore all values that preceded the corresponding bind call."""
    _trigger.reset(tokens.trigger)
    _restaurant.reset(tokens.restaurant)
    _run_id.reset(tokens.run_id)
    _invocation_id.reset(tokens.invocation_id)
    _service_name.reset(tokens.service_name)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseException):
        return type(value).__name__
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {
            key: _json_safe(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def normalize_exception_reason(reason_code: object) -> Tuple[str, str]:
    if isinstance(reason_code, str) and reason_code in SAFE_EXCEPTION_REASONS:
        return reason_code, SAFE_EXCEPTION_REASONS[reason_code]
    return (
        _FALLBACK_EXCEPTION_REASON_CODE,
        SAFE_EXCEPTION_REASONS[_FALLBACK_EXCEPTION_REASON_CODE],
    )


def sanitize_exception(error: BaseException) -> Dict[str, object]:
    """Return exception metadata without messages, values, or chained causes."""
    reason_code = getattr(error, "reason_code", None)
    safe_reason = getattr(error, "safe_reason", None)
    normalized_code, normalized_reason = normalize_exception_reason(reason_code)
    if reason_code == normalized_code and safe_reason == normalized_reason:
        return {
            "type": type(error).__name__,
            "reason_code": normalized_code,
            "safe_reason": normalized_reason,
        }

    frames: list[Dict[str, object]] = [
        {
            "filename": os.path.basename(frame.filename),
            "function": frame.name,
            "lineno": frame.lineno,
        }
        for frame in traceback.extract_tb(error.__traceback__)
    ]
    return {"type": type(error).__name__, "frames": frames}


def emit_event(level: str, event_name: str, stage: str, **fields: Any) -> None:
    """Write one compact JSON object for the current invocation."""
    event: Dict[str, Any] = {
        "service.name": _service_name.get(),
        "event.name": event_name,
        "faas.invocation_id": _invocation_id.get(),
        "run_id": _run_id.get(),
        "stage": stage,
        "log.level": level.upper(),
        "restaurant": _restaurant.get(),
        "trigger": _trigger.get(),
        **fields,
    }
    event = {
        key: _json_safe(value) for key, value in event.items() if value is not None
    }
    logger = initialize_observation_logger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(
        numeric_level,
        json.dumps(event, ensure_ascii=False, separators=(",", ":")),
    )


def measure_duration(start_ns: int) -> float:
    """Calculate elapsed milliseconds from a monotonic nanosecond reading."""
    return (time.perf_counter_ns() - start_ns) / 1_000_000


def fingerprint_source(text: str) -> Tuple[int, str]:
    """Return only UTF-8 byte length and a short source fingerprint."""
    encoded = text.encode("utf-8")
    return len(encoded), hashlib.sha256(encoded).hexdigest()[:12]


def _nonempty_string(value: object) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def build_run_id(event: Mapping[str, object], context: LambdaContext) -> str:
    """Prefer workflow execution, then event, then Lambda request identity."""
    raw_detail = event.get("detail")
    detail: Mapping[str, object] = (
        raw_detail if isinstance(raw_detail, Mapping) else {}
    )
    execution_id = (
        _nonempty_string(event.get("execution_id"))
        or _nonempty_string(event.get("executionId"))
        or _nonempty_string(detail.get("execution_id"))
        or _nonempty_string(detail.get("executionId"))
    )
    return execution_id or _nonempty_string(event.get("id")) or context.aws_request_id
