import os
import time
import json
import base64
import logging
from typing import List
from dataclasses import asdict

import openai
import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.logging_config import setup_logging
from functions.common.menu_example import student_lunch_1
from functions.common.constant import HAKSIK_ONE_DOLLOR_MORNING_PRICE, HAKSIK_LUNCH_PRICE, HAKSIK_DINNER_PRICE, \
    SOONGGURI_HAKSIK_RCD, API_BASE_URL
from functions.common.utils import parse_table_to_dict, strip_string_from_html, RequestBody, check_for_holidays


def lambda_handler(event, context):
    setup_logging(context.function_name)
    logger = logging.getLogger()
    date = event["queryStringParameters"]["date"]
    menu_dict = fetch_and_refine_haksik(date)
    logger.info(f"{date}의 학생식당의 메뉴는 {menu_dict}입니다.")

    for restrant_name, menus in menu_dict.items():
        if not menus:
            continue
        if "중식" in restrant_name:
            post_haksik_lunch(date, menus)
        elif "석식" in restrant_name:  # 석식이면 1000원 조식인 웃긴 상황이지만 어쩔 수가 없다. 추후 1000원 학식 부분 이상하면 꼭 체크!
            post_haksik_one_dollor_morning(date, menus)
        else:
            logger.error(f"중식과 석식이 아닌 메뉴가 존재합니다. {restrant_name}이라는 식사 시간이 추가된 듯 합니다.")
            raise Exception

    return {
        'statusCode': 200,
        'body': json.dumps(menu_dict, ensure_ascii=False).encode('utf-8')
    }


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_haksik_lunch(date, menus):
    lunch_form_data = asdict(RequestBody(HAKSIK_LUNCH_PRICE,menus))
    response = requests.post(url=API_BASE_URL, json=lunch_form_data,
                             params={"date": date, "restaurant": "HAKSIK", "time": "LUNCH"}, timeout=10)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_haksik_one_dollor_morning(date, menus):
    one_dollor_morning_form_data = asdict(RequestBody(HAKSIK_ONE_DOLLOR_MORNING_PRICE,menus))
    response = requests.post(url=API_BASE_URL, json=one_dollor_morning_form_data,
                             params={"date": date, "restaurant": "HAKSIK", "time": "MORNING"}, timeout=10)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def get_haksik_from_soongguri(date):
    response = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd={SOONGGURI_HAKSIK_RCD}&sdt={date}")
    response.raise_for_status()  # Ensure we got a good response
    return response




@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def chat_with_gpt_haksik(today_menu_dict):
    setup_messages = [
        {"role": "system","content": "너는 메인메뉴와 사이드메뉴를 구분하는 함수의 역할을 맡았다. input값에서 메인 메뉴와 사이드 메뉴를 구분해야해. list에는 input값에서의 메인 메뉴만 골라낸 요소들의 이름이 들어가. 만약 동일한 메인메뉴가 있다면 한 개만 리스트에 넣어. 그외에 부가적인 설명은 하지 않고 오직 json을 반환해."},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 배열을 만들고 반환해줘.:{student_lunch_1}"},
        {"role": "assistant", "content": '["오꼬노미돈까스","웨지감자튀김*케찹"]'},
    ]

    for key, value in today_menu_dict.items():
        setup_messages.append({"role": "user", "content": f"input은 바로 이거야. 여기서 메인메뉴만을 골라내어 list을 반환해줘.:{value}"})

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=setup_messages
        )

        today_menu_dict[key] = json.loads(response['choices'][0]['message']['content'])
        setup_messages.pop()

    return today_menu_dict
def fetch_and_refine_haksik(date: str):
    response = get_haksik_from_soongguri(date)
    check_for_holidays(response, date)
    menu_nm_dict = parse_table_to_dict(response)
    string_refined_dict = strip_string_from_html(menu_nm_dict)
    gpt_menu_dict = chat_with_gpt_haksik(string_refined_dict)
    return gpt_menu_dict
