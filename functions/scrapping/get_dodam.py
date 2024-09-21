import re
import json
import logging
from dataclasses import asdict

from openai import OpenAI
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import DODAM_LUNCH_PRICE, DODAM_DINNER_PRICE, SOONGGURI_DODAM_RCD, API_BASE_URL, \
    ENCRYPTED
from functions.common.utils import strip_string_from_html, parse_table_to_dict, RequestBody, check_for_holidays
from functions.common.menu_example import dodam_lunch_1

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    date = event["queryStringParameters"]["date"]

    menu_dict = fetch_and_refine_dodam(date)
    logger.info(f"{date})의 도담식당의 메뉴는 {menu_dict}입니다.")

    for restrant_name, menus in menu_dict.items():
        if not menus:
            continue
        if "중식" in restrant_name:
            post_dodam_lunch(date, menus)
        elif "석식" in restrant_name:
            post_dodam_dinner(date, menus)
        else:
            logger.error(f"중식과 석식이 아닌 메뉴가 존재합니다. {restrant_name}이라는 메뉴가 추가된 듯합니다.")
            raise Exception

    return {
        'statusCode': 200,
        'body': json.dumps(menu_dict, ensure_ascii=False).encode('utf-8')
    }


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_dodam_lunch(date, menus):
    lunch_form_data = asdict(RequestBody(DODAM_LUNCH_PRICE, menus))
    response = requests.post(url=API_BASE_URL, json=lunch_form_data,
                             params={"date": date, "restaurant": "DODAM", "time": "LUNCH"}, timeout=10)
    response.raise_for_status()  # 성공적인 응답이 아닌 경우 예외를 발생시킴

    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def post_dodam_dinner(date, menus):
    dinner_form_data = asdict(RequestBody(DODAM_DINNER_PRICE, menus))
    response = requests.post(url=API_BASE_URL, json=dinner_form_data,
                             params={"date": date, "restaurant": "DODAM", "time": "DINNER"}, timeout=10)

    response.raise_for_status()

    return response


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
def get_dodam_from_soongguri(date):
    response = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd={SOONGGURI_DODAM_RCD}&sdt={date}")
    response.raise_for_status()
    return response


def fetch_and_refine_dodam(date: str):
    response: requests.Response = get_dodam_from_soongguri(date)

    check_for_holidays(response, date)

    menu_nm_dict = parse_table_to_dict(response)
    string_refined_dict = strip_string_from_html(menu_nm_dict)
    gpt_menu_dict = chat_with_gpt_dodam(string_refined_dict)

    return gpt_menu_dict


# 재시도 조건 설정: 최대 3회 시도, 각 시도 사이에 5초 대기
@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def chat_with_gpt_dodam(today_menu_dict) -> dict:
    client = OpenAI(api_key=ENCRYPTED)
    setup_messages = [
        {"role": "system",
         "content": "너는 메인메뉴와 사이드메뉴를 구분하는 함수의 역할을 맡았다. input값에서 메인 메뉴와 사이드 메뉴를 구분해야해. list에는 input값에서의 메인 메뉴만 골라낸 요소들의 이름이 들어가. 만약 동일한 메인메뉴가 있다면 한 개만 리스트에 넣어. 메뉴 앞의 특수문자는 제외해. 그외에 부가적인 설명은 하지 않고 오직 json을 반환해."},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 배열을 만들고 반환해줘.:{dodam_lunch_1}"},
        {"role": "assistant", "content": '["오꼬노미돈까스","웨지감자튀김*케찹"]'},

    ]

    for key, value in today_menu_dict.items():
        setup_messages.append({"role": "user", "content": f"input은 바로 이거야. 여기서 메인메뉴만을 골라내어 list을 반환해줘.:{value}"})

        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=setup_messages,
            # response_format=MenuExtraction,
        )
        response_menus: list = json.loads(response.choices[0].message.content)
        refined_menus: list = [re.sub(r'[\*]+(?=[\uAC00-\uD7A3])', '', menu) for menu in response_menus]
        today_menu_dict[key] = refined_menus
        setup_messages.pop()

    return today_menu_dict
