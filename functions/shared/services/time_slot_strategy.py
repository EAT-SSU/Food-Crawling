from abc import ABC, abstractmethod
from typing import Optional, Dict, List

from functions.shared.models.model import TimeSlot, RestaurantType
from functions.shared.observability import emit_event


class TimeSlotExtractionStrategy(ABC):
    """시간대 추출 전략 인터페이스 (Strategy Pattern)"""

    @abstractmethod
    def extract_time_slot(self, menu_slot: str) -> Optional[TimeSlot]:
        """메뉴 슬롯에서 시간대를 추출합니다."""
        pass

    @abstractmethod
    def get_supported_time_slots(self) -> List[TimeSlot]:
        """지원하는 시간대 목록을 반환합니다."""
        pass

    @abstractmethod
    def get_restaurant_name(self) -> str:
        """식당 이름을 반환합니다."""
        pass


class HaksikTimeSlotStrategy(TimeSlotExtractionStrategy):
    """학생식당 시간대 추출 전략"""

    def extract_time_slot(self, menu_slot: str) -> Optional[TimeSlot]:
        if "중식" in menu_slot:
            return TimeSlot.LUNCH
        elif "석식" in menu_slot:
            # 학생식당 특수 케이스: 석식 → 1000원 조식
            emit_event(
                "INFO",
                "time_slot_remapped",
                "time_slot_extract",
                restaurant=RestaurantType.HAKSIK.english_name,
                outcome="SUCCESS",
                reason_code="DINNER_TO_ONE_DOLLAR_MORNING",
            )
            return TimeSlot.ONE_DOLLAR_MORNING
        else:
            emit_event(
                "WARNING",
                "time_slot_unsupported",
                "time_slot_extract",
                restaurant=RestaurantType.HAKSIK.english_name,
                outcome="AMBIGUOUS_EMPTY",
                reason_code="UNKNOWN_SLOT",
            )
            return None

    def get_supported_time_slots(self) -> List[TimeSlot]:
        return [TimeSlot.LUNCH, TimeSlot.ONE_DOLLAR_MORNING]

    def get_restaurant_name(self) -> str:
        return "학생식당"


class DodamTimeSlotStrategy(TimeSlotExtractionStrategy):
    """도담식당 시간대 추출 전략"""

    def extract_time_slot(self, menu_slot: str) -> Optional[TimeSlot]:
        if "조식" in menu_slot:
            emit_event(
                "INFO",
                "time_slot_unsupported",
                "time_slot_extract",
                restaurant=RestaurantType.DODAM.english_name,
                outcome="EXPECTED_EMPTY",
                reason_code="BREAKFAST_NOT_SUPPORTED",
            )
            return None
        elif "중식" in menu_slot:
            return TimeSlot.LUNCH
        elif "석식" in menu_slot:
            return TimeSlot.DINNER
        else:
            emit_event(
                "WARNING",
                "time_slot_unsupported",
                "time_slot_extract",
                restaurant=RestaurantType.DODAM.english_name,
                outcome="AMBIGUOUS_EMPTY",
                reason_code="UNKNOWN_SLOT",
            )
            return None

    def get_supported_time_slots(self) -> List[TimeSlot]:
        return [TimeSlot.LUNCH, TimeSlot.DINNER]

    def get_restaurant_name(self) -> str:
        return "도담식당"


class FacultyTimeSlotStrategy(TimeSlotExtractionStrategy):
    """교직원식당 시간대 추출 전략"""

    def extract_time_slot(self, menu_slot: str) -> Optional[TimeSlot]:
        if "중식" in menu_slot:
            return TimeSlot.LUNCH
        else:
            emit_event(
                "WARNING",
                "time_slot_unsupported",
                "time_slot_extract",
                restaurant=RestaurantType.FACULTY.english_name,
                outcome="AMBIGUOUS_EMPTY",
                reason_code="UNKNOWN_SLOT",
            )
            return None

    def get_supported_time_slots(self) -> List[TimeSlot]:
        return [TimeSlot.LUNCH]

    def get_restaurant_name(self) -> str:
        return "교직원식당"


class DormitoryTimeSlotStrategy(TimeSlotExtractionStrategy):
    """기숙사식당 시간대 추출 전략"""

    def extract_time_slot(self, menu_slot: str) -> Optional[TimeSlot]:
        if "조식" in menu_slot:
            emit_event(
                "INFO",
                "time_slot_unsupported",
                "time_slot_extract",
                restaurant=RestaurantType.DORMITORY.english_name,
                outcome="EXPECTED_EMPTY",
                reason_code="BREAKFAST_NOT_SUPPORTED",
            )
            return None
        elif "중식" in menu_slot:
            return TimeSlot.LUNCH
        elif "석식" in menu_slot:
            return TimeSlot.DINNER
        else:
            emit_event(
                "WARNING",
                "time_slot_unsupported",
                "time_slot_extract",
                restaurant=RestaurantType.DORMITORY.english_name,
                outcome="AMBIGUOUS_EMPTY",
                reason_code="UNKNOWN_SLOT",
            )
            return None

    def get_supported_time_slots(self) -> List[TimeSlot]:
        return [TimeSlot.LUNCH, TimeSlot.DINNER]

    def get_restaurant_name(self) -> str:
        return "기숙사식당"


class TimeSlotStrategyFactory:
    """시간대 추출 전략 팩토리 (Factory Pattern)"""

    _strategies: Dict[RestaurantType, TimeSlotExtractionStrategy] = {
        RestaurantType.HAKSIK: HaksikTimeSlotStrategy(),
        RestaurantType.DODAM: DodamTimeSlotStrategy(),
        RestaurantType.FACULTY: FacultyTimeSlotStrategy(),
        RestaurantType.DORMITORY: DormitoryTimeSlotStrategy(),
    }

    @classmethod
    def get_strategy(cls, restaurant_type: RestaurantType) -> TimeSlotExtractionStrategy:
        """식당 타입에 맞는 전략을 반환합니다."""
        strategy = cls._strategies.get(restaurant_type)
        if not strategy:
            raise ValueError(f"Unsupported restaurant type: {restaurant_type}")
        return strategy

    @classmethod
    def register_strategy(cls, restaurant_type: RestaurantType, strategy: TimeSlotExtractionStrategy):
        """새로운 전략을 등록합니다 (확장성)."""
        cls._strategies[restaurant_type] = strategy
