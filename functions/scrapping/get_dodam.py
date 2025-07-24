import logging
from dataclasses import asdict
import json
import logging
from dataclasses import asdict

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import DODAM_LUNCH_PRICE, DODAM_DINNER_PRICE, SOONGGURI_DODAM_RCD, API_BASE_URL, \
    DEV_API_BASE_URL
from functions.common.exceptions import HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName
from functions.common.models import RequestBody, RawMenuData, ParsedMenuData, RestaurantType, TimeSlot
from functions.common.utils import check_for_holidays, extract_all_dishes_gpt, parse_raw_menu_text_from_html, \
    send_slack_error_message

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    try:
        date = event["queryStringParameters"]["date"]
        parsed_menu_data = fetch_and_refine_dodam(date)
        post_dodam_menus(parsed_menu_data)
        logger.info(f"{date}의 도담식당의 메뉴는 {parsed_menu_data}입니다.")

        return {
            'statusCode': 200,
            'body': json.dumps(parsed_menu_data, ensure_ascii=False).encode('utf-8')
        }
    except (
            HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName) as e:
        logger.error(e)
        send_slack_error_message(e)

        return {
            'statusCode': 500,
            'body': json.dumps(str(e), ensure_ascii=False).encode('utf-8')
        }

    except Exception as e:
        logger.error(e)
        send_slack_error_message(e)

        return {
            'statusCode': 500,
            'body': json.dumps(str(e), ensure_ascii=False).encode('utf-8')
        }


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_dodam_lunch(date, menus, is_dev=False):
    lunch_form_data = asdict(RequestBody(DODAM_LUNCH_PRICE, menus))
    url = DEV_API_BASE_URL if is_dev else API_BASE_URL  # 삼항 연산
    response = requests.post(url=url, json=lunch_form_data,
                             params={"date": date, "restaurant": RestaurantType.DODAM.english_name, "time":TimeSlot.LUNCH}, timeout=10)
    response.raise_for_status()  # 성공적인 응답이 아닌 경우 예외를 발생시킴

    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_dodam_dinner(date, menus, is_dev=False):
    dinner_form_data = asdict(RequestBody(DODAM_DINNER_PRICE, menus))
    url = DEV_API_BASE_URL if is_dev else API_BASE_URL  # 삼항 연산
    response = requests.post(url=url, json=dinner_form_data,
                             params={"date": date, "restaurant": "DODAM", "time": "DINNER"}, timeout=10)

    response.raise_for_status()

    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def get_dodam_from_soongguri(date):
    response = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd={SOONGGURI_DODAM_RCD}&sdt={date}")
    response.raise_for_status()
    return response


def fetch_and_refine_dodam(date: str) -> ParsedMenuData:
    response: requests.Response = get_dodam_from_soongguri(date)
    check_for_holidays(response, date)
    raw_menu: RawMenuData = parse_raw_menu_text_from_html(response, restaurant="DODAM", date=date)
    parsed_menu_data: ParsedMenuData = extract_all_dishes_gpt(raw_menu)

    return parsed_menu_data


def post_dodam_menus(parsed_menu_data: ParsedMenuData):
    date: str = parsed_menu_data.date
    menu: dict = parsed_menu_data.menus

    for restrant_meal_time, menus in menu.items():
        if not menus:
            continue
        if "중식" in restrant_meal_time:
            post_dodam_lunch(date, menus)
            post_dodam_lunch(date, menus, is_dev=True)
        elif "석식" in restrant_meal_time:
            post_dodam_dinner(date, menus)
            post_dodam_dinner(date, menus, is_dev=True)  # dev 서버에 post
        else:
            raise WeirdRestaurantName(date, parsed_menu_data.restaurant, restrant_meal_time)


if __name__ == '__main__':
    a = fetch_and_refine_dodam('20250512')
