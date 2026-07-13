from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from functions.shared.observability import normalize_exception_reason

if TYPE_CHECKING:
    from functions.shared.models.model import RestaurantType, RawMenuData


class BaseRestaurantException(Exception):
    """기본 레스토랑 예외"""

    def __init__(
        self,
        target_date: str,
        restaurant_type: RestaurantType,
        note: Optional[str] = None,
        *,
        reason_code: str = "RESTAURANT_ERROR",
        safe_reason: Optional[str] = None,
    ):
        normalized_code, display_reason = normalize_exception_reason(reason_code)
        super().__init__(display_reason)
        self.target_date = target_date
        self.restaurant_type = restaurant_type
        self.reason_code = normalized_code
        self.safe_reason = display_reason
        self.note = display_reason

    def add_note(self, note: str) -> None:
        super().add_note(self.safe_reason)


class HolidayException(BaseRestaurantException):
    """휴무일 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, raw_data: str):
        super().__init__(
            target_date,
            restaurant_type,
            reason_code="HOLIDAY",
        )
        self.raw_data = raw_data


class MenuFetchException(BaseRestaurantException):
    """메뉴 정보 조회(fetch) 실패 예외"""

    def __init__(
        self,
        target_date: str,
        restaurant_type: RestaurantType,
        raw_menu_data: Optional[RawMenuData] = None,
        *,
        reason_code: str = "SOURCE_EMPTY",
        outcome: Optional[Any] = None,
        error_type: Optional[str] = None,
        status: Optional[int] = None,
    ):
        super().__init__(
            target_date,
            restaurant_type,
            reason_code=reason_code,
        )
        self.raw_data = raw_menu_data
        self.outcome = outcome
        self.error_type = error_type
        self.status = status


class MenuParseException(BaseRestaurantException):
    """메뉴 정보 파싱 실패 예외"""

    def __init__(
        self,
        target_date: str,
        restaurant_type: RestaurantType,
        error_details: Optional[str] = None,
        reason_code: Optional[str] = None,
    ):
        is_empty_result = bool(error_details and "메뉴를 찾지 못했습니다." in error_details)
        normalized_reason_code = (
            "PARSE_EMPTY" if reason_code == "PARSE_EMPTY" or is_empty_result else "PARSE_ERROR"
        )
        super().__init__(
            target_date,
            restaurant_type,
            reason_code=normalized_reason_code,
        )
        self.error_details = error_details


class WeirdRestaurantNameException(BaseRestaurantException):
    """정의되지 않은 식사 시간(중식/석식 외) 발견 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, meal_time: str):
        super().__init__(
            target_date,
            restaurant_type,
            reason_code="UNKNOWN_MEAL_TIME",
        )
        self.meal_time = meal_time

class MenuPostException(BaseRestaurantException):
    """Spring 서버로 메뉴 전송 시 발생하는 기본 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, details: Optional[str]):
        super().__init__(
            target_date,
            restaurant_type,
            reason_code="POST_ERROR",
        )
        self.details = details


class RetryableEmptyMenuError(BaseRestaurantException):
    """스크래핑 결과가 비어 있어(사이트 미게시) Step Functions 재시도가 필요한 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, scraped_days: int = 0):
        super().__init__(
            target_date,
            restaurant_type,
            reason_code="RETRYABLE_EMPTY",
        )
        self.scraped_days = scraped_days


class RetryableApiSendError(BaseRestaurantException):
    """파싱은 성공했으나 API 전송이 전부 실패해(대상 서버 장애) Step Functions 재시도가 필요한 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, failed_days: int = 0):
        super().__init__(
            target_date,
            restaurant_type,
            reason_code="RETRYABLE_API",
        )
        self.failed_days = failed_days
