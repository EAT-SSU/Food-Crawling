from datetime import datetime, timedelta

from pytz import timezone


def get_next_weekdays():
    seoul_tz = timezone("Asia/Seoul")
    current_date = datetime.now(seoul_tz).replace(hour=0, minute=0, second=0, microsecond=0)

    # 현재 요일이 월요일이면 7을, 그렇지 않으면 다음 주 월요일까지의 날짜 계산
    weekday = current_date.weekday()  # 현재 요일 (0: 월요일, 1: 화요일, ..., 6: 일요일)
    current_monday = current_date - timedelta(days=weekday)
    next_monday = current_monday + timedelta(days=7)

    # 날짜 범위 내의 날짜를 생성하여 리스트에 추가
    date_list = [next_monday + timedelta(days=i) for i in range(5)]
    date_list_formatted = [date.strftime("%Y%m%d") for date in date_list]

    return date_list_formatted


def get_current_weekdays():
    # 해당하는 날짜를 받으면 그 주의 월요일부터 금요일까지의 날짜를 반환
    seoul_tz = timezone("Asia/Seoul")
    current_date = datetime.now(seoul_tz).replace(hour=0, minute=0, second=0, microsecond=0)

    # 해당 주 월요일까지의 날짜 계산
    weekday = current_date.weekday()  # 현재 요일 (0: 월요일, 1: 화요일, ..., 6: 일요일)
    current_monday = current_date - timedelta(days=weekday)

    date_list = [current_monday + timedelta(days=i) for i in range(5)]
    date_list_formatted = [date.strftime("%Y%m%d") for date in date_list]

    return date_list_formatted
