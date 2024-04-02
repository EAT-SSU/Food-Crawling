import json
import requests
import datetime
from dataclasses import asdict

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.utils import make2d, RequestBody
from functions.common.constant import DORMITORY_LUNCH_PRICE,API_BASE_URL


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_dormitory_menu(date, meal_time, menus):
    dormitory_form_data = asdict(RequestBody(price=DORMITORY_LUNCH_PRICE, menuNames=menus))
    params = {
        "date": date,
        "restaurant": "DORMITORY",
        "time": get_time_of_day(meal_time)
    }
    response = requests.post(url=API_BASE_URL, json=dormitory_form_data,
                             params=params, timeout=10)
    return response


def lambda_handler(event, context):
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
                post_dormitory_menu(today["date"], meal_time, menus)

    return {
        'statusCode': 200,
        'body': json.dumps(weekly_menu, ensure_ascii=False).encode("utf-8")
    }


def get_time_of_day(meal_time):
    time_of_day_map = {
        "조식": "MORNING",
        "중식": "LUNCH",
        "석식": "DINNER"
    }
    return time_of_day_map.get(meal_time, "UNKNOWN")


class Dormitory:
    def __init__(self, date) -> None:
        self.date = datetime.strptime(date, '%Y%m%d')
        self.table = None
        self.menu_list = list()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def get_dormitory_from_ssudorm(self) -> requests.Response:
        date = self.date
        response = requests.get(
            url=f'https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php',
            params={'viewform': 'B0001_foodboard_list', 'gyear': date.year, 'gmonth': date.month, 'gday': date.day})

        response.raise_for_status()
        return response

    def refine_table(self):
        table_tag = self.soup.find("table", "boxstyle02")
        table = make2d(table_tag)
        df = pd.DataFrame(table)
        dt2 = df.rename(columns=df.iloc[0])
        dt3 = dt2.drop(dt2.index[0])
        dt3["조식"] = dt3["조식"].str.split("\r\n")
        dt3["중식"] = dt3["중식"].str.split("\r\n")
        dt3["석식"] = dt3["석식"].str.split("\r\n")
        del dt3["중.석식"]
        dt3 = dt3.set_index('날짜')
        self.table = dt3

    def get_table(self):
        for index, rows in self.table.iterrows():
            new_date = index.split()[0]
            new_date = new_date.replace("-", "")
            new_menu = {"date": new_date, "restaurant": "기숙사식당", "menu": {}}
            self.menu_list.append(new_menu)
            for col_name in self.table.columns:
                new_menu['menu'][col_name] = rows[col_name]

    def get_menu(self):
        ssudorm_response = self.get_dormitory_from_ssudorm()

        self.soup = BeautifulSoup(ssudorm_response.content, 'html.parser')
        self.refine_table()
        self.get_table()

        return self.menu_list

