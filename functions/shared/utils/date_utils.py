from datetime import datetime, timedelta

from pytz import timezone

WEEKDAYS_COUNT = 5  # 평일 (월~금)
FULL_WEEK_COUNT = 7  # 전체 주 (월~일)


def get_next_weekdays(include_weekend=False):
    seoul_tz = timezone("Asia/Seoul")
    current_date = datetime.now(seoul_tz).replace(hour=0, minute=0, second=0, microsecond=0)

    # 현재 요일이 월요일이면 7을, 그렇지 않으면 다음 주 월요일까지의 날짜 계산
    weekday = current_date.weekday()  # 현재 요일 (0: 월요일, 1: 화요일, ..., 6: 일요일)
    current_monday = current_date - timedelta(days=weekday)
    next_monday = current_monday + timedelta(days=FULL_WEEK_COUNT)

    # 날짜 범위 내의 날짜를 생성하여 리스트에 추가
    days_count = FULL_WEEK_COUNT if include_weekend else WEEKDAYS_COUNT
    date_list = [next_monday + timedelta(days=i) for i in range(days_count)]
    date_list_formatted = [date.strftime("%Y%m%d") for date in date_list]

    return date_list_formatted


def get_current_weekdays(include_weekend=False):
    # 해당하는 날짜를 받으면 그 주의 월요일부터 금요일까지의 날짜를 반환
    seoul_tz = timezone("Asia/Seoul")
    current_date = datetime.now(seoul_tz).replace(hour=0, minute=0, second=0, microsecond=0)

    # 해당 주 월요일까지의 날짜 계산
    weekday = current_date.weekday()  # 현재 요일 (0: 월요일, 1: 화요일, ..., 6: 일요일)
    current_monday = current_date - timedelta(days=weekday)

    days_count = FULL_WEEK_COUNT if include_weekend else WEEKDAYS_COUNT
    date_list = [current_monday + timedelta(days=i) for i in range(days_count)]
    date_list_formatted = [date.strftime("%Y%m%d") for date in date_list]

    return date_list_formatted
