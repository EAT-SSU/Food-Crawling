import pytest

from functions.common.utils import get_next_weekdays, get_current_weekdays


# Test get_next_weekdays를 하는 여러 테스트 케이스를 작성해줘.

@pytest.mark.unit
def test_get_next_weekdays_with_param():
    weekdays = get_next_weekdays()

    # 실제로 다음 주의 월요일부터 금요일 날짜가 나와야 함
    assert len(weekdays) == 5 and all(isinstance(day, str) for day in weekdays)  and weekdays == ['20241014', '20241015', '20241016', '20241017', '20241018']

@pytest.mark.unit
def test_get_current_weekdays():
    weekdays = get_current_weekdays()

    # 실제로 지금 주의 월요일부터 금요일 날짜가 나와야 함
    assert len(weekdays) == 5 and all(isinstance(day, str) for day in weekdays)  and weekdays == ['20241007', '20241008', '20241009', '20241010', '20241011']
