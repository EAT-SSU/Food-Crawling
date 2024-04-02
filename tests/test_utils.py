from functions.common.utils import get_next_weekdays, get_current_weekdays

# Test get_next_weekdays를 하는 여러 테스트 케이스를 작성해줘.

def test_get_next_weekdays_with_param():
    weekdays = get_next_weekdays()

    # 실제로 다음 주의 월요일부터 금요일 날짜가 나와야 함
    assert len(weekdays) == 5 and all(isinstance(day, str) for day in weekdays)  and weekdays == ['20240408', '20240409', '20240410', '20240411', '20240412']

def test_get_current_weekdays():
    weekdays = get_current_weekdays()

    # 실제로 지금 주의 월요일부터 금요일 날짜가 나와야 함
    assert len(weekdays) == 5 and all(isinstance(day, str) for day in weekdays)  and weekdays == ['20240401', '20240402', '20240403', '20240404', '20240405']