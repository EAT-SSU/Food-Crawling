import json
import traceback

import pytest

from functions.shared.models.exceptions import (
    BaseRestaurantException,
    HolidayException,
    MenuFetchException,
    MenuParseException,
    MenuPostException,
    RetryableApiSendError,
    RetryableEmptyMenuError,
    WeirdRestaurantNameException,
)
from functions.shared.models.model import (
    ParsedMenuData,
    RawMenuData,
    ResponseBuilder,
    RestaurantType,
)
from functions.shared.observability import sanitize_exception


SENTINEL = "<html>SECRET_TOKEN"
MALICIOUS_DETAIL = f"provider error {SENTINEL} https://provider.invalid/token"


class MaliciousErrorValue:
    def __str__(self) -> str:
        return MALICIOUS_DETAIL


class SpoofedReasonException(Exception):
    def __init__(self):
        super().__init__("fixed custom failure")
        self.reason_code = MALICIOUS_DETAIL
        self.safe_reason = MALICIOUS_DETAIL


def _serialized(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def test_holiday_keeps_raw_data_out_of_string_args_and_note():
    error = HolidayException("20260712", RestaurantType.DODAM, SENTINEL)
    error.add_note(SENTINEL)

    assert error.raw_data == SENTINEL
    assert error.reason_code == "HOLIDAY"
    assert error.safe_reason == "휴무일"
    assert str(error) == "휴무일"
    assert SENTINEL not in _serialized(error.args)
    assert SENTINEL not in str(error.note)
    assert SENTINEL not in _serialized(error.__notes__)


def test_menu_fetch_keeps_raw_object_only_as_internal_diagnostic():
    raw_data = RawMenuData(
        date="20260712",
        restaurant=RestaurantType.HAKSIK,
        menu_texts={"중식1": SENTINEL},
    )
    error = MenuFetchException("20260712", RestaurantType.HAKSIK, raw_data)

    assert error.raw_data is raw_data
    assert error.reason_code == "SOURCE_EMPTY"
    assert error.safe_reason == "메뉴 미게시 또는 원본 누락"
    assert SENTINEL not in str(error)
    assert SENTINEL not in _serialized(error.args)
    assert SENTINEL not in str(error.note)


def test_direct_base_exception_normalizes_untrusted_reason_fields():
    error = BaseRestaurantException(
        "20260712",
        RestaurantType.DODAM,
        note=MALICIOUS_DETAIL,
        reason_code=MALICIOUS_DETAIL,
        safe_reason=MALICIOUS_DETAIL,
    )
    try:
        raise error
    except BaseRestaurantException as raised:
        rendered_traceback = "".join(
            traceback.format_exception(type(raised), raised, raised.__traceback__)
        )

    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        success=False,
        error_slots={"base": error},
    )
    response = ResponseBuilder.create_error_response(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        error=error,
    )

    assert error.reason_code == "RESTAURANT_ERROR"
    assert error.safe_reason == "메뉴 처리 실패"
    assert str(error) == "메뉴 처리 실패"
    rendered = _serialized(
        {
            "args": error.args,
            "note": error.note,
            "parsed": parsed.to_dict(),
            "response": json.loads(response["body"]),
        }
    )
    assert SENTINEL not in rendered
    assert "provider.invalid" not in rendered
    assert SENTINEL not in rendered_traceback
    assert "provider.invalid" not in rendered_traceback


def test_custom_exception_cannot_spoof_safe_reason_metadata():
    caught = None
    try:
        raise SpoofedReasonException()
    except SpoofedReasonException as error:
        caught = error
        sanitized = sanitize_exception(error)
        rendered_traceback = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )

    assert caught is not None
    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        success=False,
        error_slots={"spoofed": caught},
    )
    response = ResponseBuilder.create_error_response(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        error=caught,
    )

    assert sanitized["type"] == "SpoofedReasonException"
    assert "reason_code" not in sanitized
    assert "safe_reason" not in sanitized
    rendered = _serialized(
        {
            "sanitized": sanitized,
            "parsed": parsed.to_dict(),
            "response": json.loads(response["body"]),
        }
    )
    assert SENTINEL not in rendered
    assert "provider.invalid" not in rendered
    assert SENTINEL not in rendered_traceback
    assert "provider.invalid" not in rendered_traceback


@pytest.mark.parametrize(
    ("reason_code", "safe_reason"),
    [
        ("RESTAURANT_ERROR", "메뉴 처리 실패"),
        ("HOLIDAY", "휴무일"),
        ("SOURCE_EMPTY", "메뉴 미게시 또는 원본 누락"),
        ("SOURCE_SCHEMA_CHANGED", "메뉴 원본 구조 변경"),
        ("SOURCE_HTTP_ERROR", "메뉴 원본 조회 실패"),
        ("PARSE_EMPTY", "메뉴 파싱 실패"),
        ("PARSE_ERROR", "메뉴 파싱 실패"),
        ("UNKNOWN_MEAL_TIME", "지원하지 않는 식사 시간"),
        ("POST_ERROR", "메뉴 저장 실패"),
        ("RETRYABLE_EMPTY", "메뉴 미게시로 재시도 필요"),
        ("RETRYABLE_API", "메뉴 저장 재시도 필요"),
    ],
)
def test_base_exception_uses_canonical_reason_mapping(reason_code, safe_reason):
    error = BaseRestaurantException(
        "20260712",
        RestaurantType.DODAM,
        note=MALICIOUS_DETAIL,
        reason_code=reason_code,
        safe_reason=MALICIOUS_DETAIL,
    )

    assert error.reason_code == reason_code
    assert error.safe_reason == safe_reason
    assert str(error) == safe_reason


def test_unknown_meal_time_is_retained_only_as_internal_diagnostic():
    error = WeirdRestaurantNameException(
        "20260712", RestaurantType.DODAM, SENTINEL
    )
    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        success=False,
        error_slots={"unknown": error},
    )
    response = ResponseBuilder.create_error_response(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        error=error,
    )

    assert error.meal_time == SENTINEL
    assert error.reason_code == "UNKNOWN_MEAL_TIME"
    assert error.safe_reason == "지원하지 않는 식사 시간"
    assert str(error) == "지원하지 않는 식사 시간"
    serialized = _serialized(
        {
            "args": error.args,
            "note": error.note,
            "safe_reason": error.safe_reason,
            "parsed": parsed.to_dict(),
            "response": json.loads(response["body"]),
        }
    )
    assert SENTINEL not in serialized


@pytest.mark.parametrize(
    ("error", "reason_code", "safe_reason"),
    [
        (
            MenuParseException(
                "20260712",
                RestaurantType.FACULTY,
                error_details=f"provider detail {SENTINEL}",
            ),
            "PARSE_ERROR",
            "메뉴 파싱 실패",
        ),
        (
            MenuParseException(
                "20260712",
                RestaurantType.FACULTY,
                error_details="메뉴 슬롯 '중식1'에서 메뉴를 찾지 못했습니다.",
            ),
            "PARSE_EMPTY",
            "메뉴 파싱 실패",
        ),
        (
            MenuPostException(
                "20260712",
                RestaurantType.DORMITORY,
                details=f"provider detail {SENTINEL}",
            ),
            "POST_ERROR",
            "메뉴 저장 실패",
        ),
        (
            RetryableEmptyMenuError("20260712", RestaurantType.DORMITORY, 0),
            "RETRYABLE_EMPTY",
            "메뉴 미게시로 재시도 필요",
        ),
        (
            RetryableApiSendError("20260712", RestaurantType.DORMITORY, 2),
            "RETRYABLE_API",
            "메뉴 저장 재시도 필요",
        ),
    ],
)
def test_domain_exceptions_use_allowlisted_safe_reasons(error, reason_code, safe_reason):
    assert error.reason_code == reason_code
    assert error.safe_reason == safe_reason
    assert str(error) == safe_reason
    assert SENTINEL not in str(error)
    assert SENTINEL not in _serialized(error.args)
    assert SENTINEL not in str(error.note)


def test_chained_unexpected_exception_omits_messages_and_preserves_frames():
    try:
        try:
            raise ValueError(SENTINEL)
        except ValueError as cause:
            raise RuntimeError(f"provider detail {SENTINEL}") from cause
    except RuntimeError as error:
        sanitized = sanitize_exception(error)

    assert sanitized["type"] == "RuntimeError"
    frames = sanitized["frames"]
    assert isinstance(frames, list)
    assert frames
    last_frame = frames[-1]
    assert isinstance(last_frame, dict)
    assert set(last_frame) == {"filename", "function", "lineno"}
    serialized = _serialized(sanitized)
    assert SENTINEL not in serialized
    assert "provider detail" not in serialized
    assert "ValueError" not in serialized


def test_parsed_menu_serializes_string_and_exception_errors_safely():
    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        success=False,
        error_slots={
            "legacy": "메뉴 파싱 실패",
            "domain": MenuParseException(
                "20260712", RestaurantType.DODAM, error_details=SENTINEL
            ),
            "unexpected": ValueError(SENTINEL),
        },
    )

    errors = parsed.to_dict()["error_slots"]

    assert errors["legacy"] == "메뉴 파싱 실패"
    assert errors["domain"] == {
        "type": "MenuParseException",
        "reason_code": "PARSE_ERROR",
        "safe_reason": "메뉴 파싱 실패",
    }
    assert errors["unexpected"] == "ValueError"
    assert SENTINEL not in _serialized(errors)


def test_parsed_menu_preserves_only_explicitly_allowlisted_legacy_strings():
    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        success=False,
        error_slots={
            "old": "파싱 실패",
            "current": "메뉴 파싱 실패",
        },
    )

    assert parsed.to_dict()["error_slots"] == {
        "old": "파싱 실패",
        "current": "메뉴 파싱 실패",
    }


@pytest.mark.parametrize(
    "unsafe_value",
    [
        MALICIOUS_DETAIL,
        {"provider": MALICIOUS_DETAIL},
        [MALICIOUS_DETAIL],
        MaliciousErrorValue(),
    ],
)
def test_unknown_error_slot_values_use_fixed_fallback_at_all_boundaries(unsafe_value):
    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={"중식1": []},
        success=False,
        error_slots={"중식1": unsafe_value},
    )

    serialized = parsed.to_dict()
    response = ResponseBuilder.create_success_response(parsed)
    response_body = json.loads(response["body"])

    assert serialized["error_slots"] == {"중식1": "처리 실패"}
    assert response_body["parsing_errors"] == {"중식1": "처리 실패"}
    rendered = _serialized({"parsed": serialized, "response": response_body})
    assert SENTINEL not in rendered
    assert "provider error" not in rendered
    assert "provider.invalid" not in rendered


def test_response_builder_serializes_success_errors_with_safe_fields():
    parsed = ParsedMenuData(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={"중식1": []},
        success=False,
        error_slots={
            "중식1": MenuParseException(
                "20260712", RestaurantType.DODAM, error_details=SENTINEL
            )
        },
    )

    response = ResponseBuilder.create_success_response(parsed)
    body = json.loads(response["body"])

    assert body["parsing_errors"]["중식1"]["reason_code"] == "PARSE_ERROR"
    assert body["parsing_errors"]["중식1"]["safe_reason"] == "메뉴 파싱 실패"
    assert SENTINEL not in response["body"]


def test_response_builder_serializes_domain_error_without_provider_detail():
    error = MenuPostException(
        "20260712",
        RestaurantType.DODAM,
        details=f"https://provider.invalid/token {SENTINEL}",
    )

    response = ResponseBuilder.create_error_response(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        error=error,
    )
    body = json.loads(response["body"])

    assert body["error"] == {
        "type": "MenuPostException",
        "reason_code": "POST_ERROR",
        "safe_reason": "메뉴 저장 실패",
    }
    assert body["error_type"] == "MenuPostException"
    assert SENTINEL not in response["body"]
    assert "provider.invalid" not in response["body"]
