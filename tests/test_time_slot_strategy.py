from functions.shared.models.model import RestaurantType, TimeSlot
from functions.shared.services.time_slot_strategy import (
    TimeSlotStrategyFactory, HaksikTimeSlotStrategy, DodamTimeSlotStrategy,
    FacultyTimeSlotStrategy, DormitoryTimeSlotStrategy
)


class TestTimeSlotStrategies:
    """시간대 추출 전략들 테스트"""

    def test_haksik_strategy(self):
        """학생식당 전략 테스트"""
        strategy = HaksikTimeSlotStrategy()

        assert strategy.extract_time_slot("중식1") == TimeSlot.LUNCH
        assert strategy.extract_time_slot("석식1") == TimeSlot.ONE_DOLLAR_MORNING  # 특수 케이스
        assert strategy.extract_time_slot("알 수 없는 메뉴") is None

        supported_times = strategy.get_supported_time_slots()
        assert TimeSlot.LUNCH in supported_times
        assert TimeSlot.ONE_DOLLAR_MORNING in supported_times

    def test_dodam_strategy(self):
        """도담식당 전략 테스트"""
        strategy = DodamTimeSlotStrategy()

        assert strategy.extract_time_slot("중식1") == TimeSlot.LUNCH
        assert strategy.extract_time_slot("석식1") == TimeSlot.DINNER
        assert strategy.extract_time_slot("조식1") is None  # 조식 운영 안함

        supported_times = strategy.get_supported_time_slots()
        assert TimeSlot.LUNCH in supported_times
        assert TimeSlot.DINNER in supported_times
        assert TimeSlot.ONE_DOLLAR_MORNING not in supported_times

    def test_faculty_strategy(self):
        """교직원식당 전략 테스트"""
        strategy = FacultyTimeSlotStrategy()

        assert strategy.extract_time_slot("중식1") == TimeSlot.LUNCH
        assert strategy.extract_time_slot("석식1") is None  # 점심만 운영

        supported_times = strategy.get_supported_time_slots()
        assert TimeSlot.LUNCH in supported_times
        assert len(supported_times) == 1

    def test_dormitory_strategy(self):
        """기숙사식당 전략 테스트"""
        strategy = DormitoryTimeSlotStrategy()

        assert strategy.extract_time_slot("중식") == TimeSlot.LUNCH
        assert strategy.extract_time_slot("석식") == TimeSlot.DINNER
        assert strategy.extract_time_slot("조식") is None  # 조식 운영 안함

    def test_strategy_factory(self):
        """전략 팩토리 테스트"""
        haksik_strategy = TimeSlotStrategyFactory.get_strategy(RestaurantType.HAKSIK)
        assert isinstance(haksik_strategy, HaksikTimeSlotStrategy)

        dodam_strategy = TimeSlotStrategyFactory.get_strategy(RestaurantType.DODAM)
        assert isinstance(dodam_strategy, DodamTimeSlotStrategy)

        faculty_strategy = TimeSlotStrategyFactory.get_strategy(RestaurantType.FACULTY)
        assert isinstance(faculty_strategy, FacultyTimeSlotStrategy)

        dormitory_strategy = TimeSlotStrategyFactory.get_strategy(RestaurantType.DORMITORY)
        assert isinstance(dormitory_strategy, DormitoryTimeSlotStrategy)