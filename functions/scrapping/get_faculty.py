import json
from dataclasses import asdict
from logging import getLogger

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import SOONGGURI_FACULTY_RCD, FACULTY_LUNCH_PRICE, DEV_API_BASE_URL, API_BASE_URL
from functions.common.models import ParsedMenuData, RawMenuData, RequestBody
from functions.common.utils import check_for_holidays, parse_raw_menu_text_from_html, extract_all_dishes_gpt

logger = getLogger(__name__)

def lambda_handler(event, context):
    date = event["queryStringParameters"]["date"]

    parsed_menu_data = fetch_and_refine_faculty(date)
    post_faculty_menu(parsed_menu_data)
    logger.info(f"{date}의 교직원 식당의 메뉴는 {parsed_menu_data}입니다.")

    return {
        'statusCode': 200,
        'body': json.dumps(parsed_menu_data, ensure_ascii=False).encode('utf-8')
    }


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_faculty_lunch(date, menus, is_dev=False):
    lunch_form_data = asdict(RequestBody(FACULTY_LUNCH_PRICE, menus))
    url = DEV_API_BASE_URL if is_dev else API_BASE_URL  # 삼항 연산
    response = requests.post(url=url, json=lunch_form_data,
                             params={"date": date, "restaurant": "HAKSIK", "time": "LUNCH"}, timeout=10)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def get_faculty_from_soongguri(date):
    response = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd={SOONGGURI_FACULTY_RCD}&sdt={date}")
    response.raise_for_status()  # Ensure we got a good response
    return response


def fetch_and_refine_faculty(date: str) -> ParsedMenuData:
    try:
        response: requests.Response = get_faculty_from_soongguri(date)
        check_for_holidays(response, date)
        raw_menu: RawMenuData = parse_raw_menu_text_from_html(response, restaurant="교직원식당", date=date)
        parsed_menu_data: ParsedMenuData = extract_all_dishes_gpt(raw_menu)
    except:
        pass


    return parsed_menu_data

def post_faculty_menu(parsed_menu_data:ParsedMenuData):
    date = parsed_menu_data.date
    menu = parsed_menu_data.menus

    for restrant_name, menus in menu.items():
        if not menus:
            continue
        if "중식" in restrant_name:
            post_faculty_lunch(date, menus)
            post_faculty_lunch(date, menus, is_dev=True)
        else:
            logger.error(f"중식과 석식이 아닌 메뉴가 존재합니다. {restrant_name}이라는 식사 시간이 추가된 듯 합니다.")
            raise Exception



if __name__ == '__main__':
    a = fetch_and_refine_faculty(date='20250714')
