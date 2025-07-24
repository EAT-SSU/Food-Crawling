import json
from datetime import datetime

import pytest

from functions.scrapping.get_dormitory import Dormitory
from functions.scrapping.get_dormitory import post_dormitory_menu


@pytest.mark.integration
def test_lambda_handler(event, context):
    weekly_dorm = Dormitory(event["queryStringParameters"]["date"])
    weekly_menu = weekly_dorm.get_menu()

    for today in weekly_menu:
        date_obj = datetime.strptime(today["date"], "%Y%m%d")
        is_weekend = date_obj.weekday() >= 5  # 토요일 또는 일요일

        for meal_time, menus in today["menu"].items():
            # 주말에는 조식을 운영하지 않음
            if is_weekend and meal_time == "조식":
                continue

            # '운영'이 포함된 메뉴가 없을 경우에만 메뉴 게시
            if not any("운영" in menu for menu in menus):
                post_dormitory_menu(today["date"], meal_time, menus, is_dev=False)  # production 서버에 post하는 부분
                post_dormitory_menu(today["date"], meal_time, menus, is_dev=True)  # dev 서버에도 post하는 부분

    return {
        'statusCode': 200,
        'body': json.dumps(weekly_menu, ensure_ascii=False).encode("utf-8")
    }

if __name__ == '__main__':
    test_lambda_handler({"queryStringParameters": {"date": "20241021"}}, None)
