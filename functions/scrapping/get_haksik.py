import json
import logging
from dataclasses import asdict

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import HAKSIK_ONE_DOLLOR_MORNING_PRICE, HAKSIK_LUNCH_PRICE, SOONGGURI_HAKSIK_RCD, \
    API_BASE_URL, DEV_API_BASE_URL
from functions.common.exceptions import HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName
from functions.common.models import ParsedMenuData, RawMenuData, RequestBody
from functions.common.utils import check_for_holidays, parse_raw_menu_text_from_html, extract_all_dishes_gpt, \
    send_slack_error_message

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    try:
        date = event["queryStringParameters"]["date"]
        parsed_menu_data = fetch_and_refine_haksik(date)
        post_haksik_menus(parsed_menu_data)
        logger.info(f"{date}의 학생식당의 메뉴는 {parsed_menu_data}입니다.")

        return {
            'statusCode': 200,
            'body': json.dumps(parsed_menu_data, ensure_ascii=False).encode('utf-8')
        }
    except (HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName) as e:
        logger.error(e)
        send_slack_error_message(e)

        return {
            'statusCode': 500,
            'body': json.dumps(str(e), ensure_ascii=False).encode('utf-8')
        }


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_haksik_lunch(date, menus, is_dev=False):
    lunch_form_data = asdict(RequestBody(HAKSIK_LUNCH_PRICE, menus))
    url = DEV_API_BASE_URL if is_dev else API_BASE_URL  # 삼항 연산
    response = requests.post(url=url, json=lunch_form_data,
                             params={"date": date, "restaurant": "HAKSIK", "time": "LUNCH"}, timeout=10)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_haksik_one_dollor_morning(date, menus, is_dev=False):
    one_dollor_morning_form_data = asdict(RequestBody(HAKSIK_ONE_DOLLOR_MORNING_PRICE, menus))
    url = DEV_API_BASE_URL if is_dev else API_BASE_URL  # 삼항 연산
    response = requests.post(url=url, json=one_dollor_morning_form_data,
                             params={"date": date, "restaurant": "HAKSIK", "time": "MORNING"}, timeout=10)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def get_haksik_from_soongguri(date):
    response = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd={SOONGGURI_HAKSIK_RCD}&sdt={date}")
    response.raise_for_status()  # Ensure we got a good response
    return response


def fetch_and_refine_haksik(date: str) -> ParsedMenuData:
    response: requests.Response = get_haksik_from_soongguri(date)
    check_for_holidays(response, date)
    raw_menu: RawMenuData = parse_raw_menu_text_from_html(response, restaurant="학생식당", date=date)
    parsed_menu_data: ParsedMenuData = extract_all_dishes_gpt(raw_menu)

    return parsed_menu_data


def post_haksik_menus(parsed_menu_data: ParsedMenuData):
    date: str = parsed_menu_data.date
    menu: dict = parsed_menu_data.menus

    for restrant_meal_time, menus in menu.items():
        if "중식" in restrant_meal_time:
            post_haksik_lunch(date, menus)
            post_haksik_lunch(date, menus, is_dev=True)
        elif "석식" in restrant_meal_time:  # 석식이면 1000원 조식인 웃긴 상황이지만 어쩔 수가 없다. 추후 1000원 학식 부분 이상하면 꼭 체크!
            post_haksik_one_dollor_morning(date, menus)
            post_haksik_one_dollor_morning(date, menus, is_dev=True)  # dev 서버에 post
        else:
            raise WeirdRestaurantName(date, parsed_menu_data.restaurant, restrant_meal_time)
    if parsed_menu_data.error_slots:
        send_slack_error_message(MenuParseException(target_date=date, error_details=""))


if __name__ == '__main__':
    a = fetch_and_refine_haksik('20250505')
