import logging
from dataclasses import asdict
from typing import List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import DODAM_LUNCH_PRICE, DODAM_DINNER_PRICE, SOONGGURI_DODAM_RCD, API_BASE_URL, \
    DEV_API_BASE_URL
from functions.common.models import RequestBody, RawMenuData, ParsedMenuData
from functions.common.utils import check_for_holidays, extract_main_dishes_gpt, get_next_weekdays, \
    parse_raw_menu_text_from_html, create_github_summary, send_slack_message, get_current_weekdays

logger = logging.getLogger()


def schedule_dodam(is_current_week: bool = False, manual_dates: Optional[List[str]] = None):
    if manual_dates:
        weekdays = manual_dates
    else:
        weekdays = get_current_weekdays() if is_current_week else get_next_weekdays()
    results: List[ParsedMenuData] = []  # 모든 ParsedMenuData를 저장

    for date in weekdays:
        whole_day_menu: ParsedMenuData = fetch_and_refine_dodam(date)

        if whole_day_menu.is_empty:
            logger.warning(f'{date} 메뉴 전체가 비어있음')
            results.append(whole_day_menu)
            continue

        for restaurant_name, menus in whole_day_menu.menus.items():
            try:
                if not menus:
                    logger.warning(f'{date}_{restaurant_name}은 메뉴 없음')
                    continue

                if "중식" in restaurant_name:
                    logger.info(f'{date}_{restaurant_name} (중식): {menus}')
                    res = post_dodam_lunch(date, menus, is_dev=True)
                    res.raise_for_status()
                elif "석식" in restaurant_name:
                    logger.info(f'{date}_{restaurant_name} (석식): {menus}')
                    res = post_dodam_dinner(date, menus, is_dev=True)
                    res.raise_for_status()
                else:
                    raise Exception(f'이상한 식당 이름: {restaurant_name}')

            except Exception as e:
                logger.exception(f'{date}_{restaurant_name} 전송 오류: {e}')
                whole_day_menu.add_error(restaurant_name, str(e))  # 에러 기록
                continue

        results.append(whole_day_menu)

    [send_slack_message(result) for result in results]
    create_github_summary(results)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_dodam_lunch(date, menus, is_dev=False):
    lunch_form_data = asdict(RequestBody(DODAM_LUNCH_PRICE, menus))
    url = DEV_API_BASE_URL if is_dev else API_BASE_URL  # 삼항 연산
    response = requests.post(url=url, json=lunch_form_data,
                             params={"date": date, "restaurant": "DODAM", "time": "LUNCH"}, timeout=10)
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

    parsed_menu_data: ParsedMenuData = extract_main_dishes_gpt(raw_menu)

    return parsed_menu_data


if __name__ == '__main__':
    schedule_dodam(manual_dates=["20240318","20240319"])