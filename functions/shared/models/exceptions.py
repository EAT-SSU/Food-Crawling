from typing import Optional

from functions.shared.models.model import RestaurantType, RawMenuData


class BaseRestaurantException(Exception):
    """기본 레스토랑 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, note: str = None):
        # 1. 기본 메시지를 생성합니다.
        base_message = f"{restaurant_type}({target_date}) "

        # 2. 추가 노트(note)가 있으면 기본 메시지에 결합합니다.
        message = f"{base_message}: {note}" if note else base_message

        super().__init__(message)

        # 나중에 예외 객체에서 참고할 수 있도록 속성을 저장합니다.
        self.target_date = target_date
        self.restaurant_type = restaurant_type
        self.note = note


class HolidayException(BaseRestaurantException):
    """휴무일 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, raw_data: str):
        note = f"해당일은 휴무일입니다. (원본 데이터: {raw_data})"
        super().__init__(target_date, restaurant_type, note)
        self.raw_data = raw_data


class MenuFetchException(BaseRestaurantException):
    """메뉴 정보 조회(fetch) 실패 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, raw_menu_data: Optional[RawMenuData] = None):
        note = f"메뉴 정보 조회에 실패했습니다. (원본 데이터: {raw_menu_data})"
        super().__init__(target_date, restaurant_type, note)
        self.raw_data = raw_menu_data


class MenuParseException(BaseRestaurantException):
    """메뉴 정보 파싱 실패 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, error_details: Optional[str]=None):
        note = f"메뉴 정보 파싱에 실패했습니다. (오류 상세: {error_details})"
        super().__init__(target_date, restaurant_type, note)
        self.error_details = error_details


class WeirdRestaurantNameException(BaseRestaurantException):
    """정의되지 않은 식사 시간(중식/석식 외) 발견 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, meal_time: str):
        note = f"정의되지 않은 식사 시간 '{meal_time}'이 발견되었습니다."
        super().__init__(target_date, restaurant_type, note)
        self.meal_time = meal_time

class MenuPostException(BaseRestaurantException):
    """Spring 서버로 메뉴 전송 시 발생하는 기본 예외"""

    def __init__(self,target_date: str, restaurant_type: RestaurantType, details: Optional[str]):
        note = details
        super().__init__(target_date, restaurant_type, note)
        self.details = details


class RetryableEmptyMenuError(BaseRestaurantException):
    """스크래핑 결과가 비어 있어(사이트 미게시) Step Functions 재시도가 필요한 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, scraped_days: int = 0):
        note = f"스크래핑 결과가 비어 있습니다. (수집 일수: {scraped_days}) 사이트 메뉴 미게시로 추정되어 재시도가 필요합니다."
        super().__init__(target_date, restaurant_type, note)
        self.scraped_days = scraped_days


class RetryableApiSendError(BaseRestaurantException):
    """파싱은 성공했으나 API 전송이 전부 실패해(대상 서버 장애) Step Functions 재시도가 필요한 예외"""

    def __init__(self, target_date: str, restaurant_type: RestaurantType, failed_days: int = 0):
        note = f"파싱된 메뉴가 있으나 API 전송에 전부 실패했습니다. (실패 일수: {failed_days}) 대상 서버 장애로 추정되어 재시도가 필요합니다."
        super().__init__(target_date, restaurant_type, note)
        self.failed_days = failed_days
