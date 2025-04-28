import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from pytz import timezone
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import GPT_FUNCTION_TOOLS, GPT_SYSTEM_PROMPT, GPT_MODEL, ENCRYPTED, SLACK_WEBHOOK_URL
from functions.common.models import RawMenuData, RestaurantType, ParsedMenuData

logger = logging.getLogger()


def parse_raw_menu_text_from_html(response: requests.Response, restaurant: RestaurantType, date: str)-> RawMenuData:
    menu_dict = parse_table_to_dict(response)
    stripped_menu_dict = strip_string_from_html(menu_dict)

    raw_menu_data = RawMenuData(date=date, restaurant=restaurant, menu_texts=stripped_menu_dict)

    return raw_menu_data


def parse_table_to_dict(response: requests.Response):
    soup = BeautifulSoup(response.content, "html.parser")
    tr_list = soup.find_all('tr')
    menu_nm_dict = {}
    for tr_tag in tr_list:
        td_tag = tr_tag.find('td', {'class': 'menu_nm'})
        if td_tag:
            menu_nm_dict[td_tag.text] = tr_tag
    return menu_nm_dict


def strip_string_from_html(menu_dict):
    for key, value in menu_dict.items():
        new_text = " ".join(text for text in value.stripped_strings)
        menu_dict[key] = new_text
    return menu_dict


def find_rows(table):
    return table.find_all('tr')


def find_cells(row):
    cells = []

    ths = row.find_all('th', recursive=False)
    if ths:
        cells.extend(ths)
    tds = row.find_all('td', recursive=False)
    if tds:
        cells.extend(tds)

    return cells


def insert_colspans(twod):
    for rdx, row in enumerate(twod):
        for cdx, cell in enumerate(row):
            cell_colspan = cell.get('colspan')
            if cell_colspan and cell_colspan.isdigit() and not cell.get('col_done'):
                cell['col_done'] = True
                for x in range(1, int(cell_colspan)):
                    if rdx == 0:
                        twod[rdx].insert(cdx, cell)
                    else:
                        if len(twod[rdx]) < len(twod[rdx - 1]):
                            twod[rdx].insert(cdx, cell)

    # flip done attributes back because state is saved on following iterations
    for rdx, row in enumerate(twod):
        for cdx, cell in enumerate(row):
            if cell.get('col_done'):
                cell['col_done'] = False

    return twod


def insert_rowspans(twod):
    for rdx, row in enumerate(twod):
        for cdx, cell in enumerate(row):
            cell_rowspan = cell.get('rowspan')
            if cell_rowspan and cell_rowspan.isdigit() and not cell.get('row_done'):
                cell['row_done'] = True
                for x in range(1, int(cell_rowspan)):
                    if rdx + x < len(twod):
                        twod[rdx + x].insert(cdx, cell)

    # flip done attributes back because state is saved on following iterations
    for rdx, row in enumerate(twod):
        for cdx, cell in enumerate(row):
            if cell.get('row_done'):
                cell['row_done'] = False

    return twod


def textonly(twod):
    text2d = []

    for rdx, row in enumerate(twod):
        text2d.append([])
        for cell in row:
            text2d[rdx].append(cell.text.strip())

    return text2d


def make2d(table, text_only=True):
    twod = []

    for rdx, row in enumerate(find_rows(table)):
        twod.append([])
        for cell in find_cells(row):
            twod[rdx].append(cell)

    twod = insert_colspans(twod)
    twod = insert_rowspans(twod)

    if text_only:
        twod = textonly(twod)

    return twod


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def extract_main_dishes_gpt(today_raw_menu: RawMenuData) -> ParsedMenuData:
    """
    GPT를 사용하여 메뉴 텍스트에서 메인 메뉴를 추출합니다.

    Args:
        today_raw_menu: 원시 메뉴 데이터

    Returns:
        ParsedMenuData: 파싱된 메뉴 데이터
    """
    client = OpenAI(api_key=ENCRYPTED)
    result_dict = {}
    errors = {}

    for key, value in today_raw_menu.menu_texts.items():
        try:
            logger.info(f"메뉴 처리 중: {key}")

            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": GPT_SYSTEM_PROMPT},
                    {"role": "user", "content": f"다음 메뉴 목록에서 메인 메뉴만 추출해주세요: {value}"}
                ],
                tools=GPT_FUNCTION_TOOLS,
                tool_choice={"type": "function", "function": {"name": "extract_main_menus"}}
            )

            # 함수 호출 결과 파싱
            tool_call = response.choices[0].message.tool_calls[0]
            function_args = json.loads(tool_call.function.arguments)
            main_menus = function_args.get("main_menus", [])

            # 빈 결과 확인
            if not main_menus:
                logger.warning(f"메뉴 '{key}'에서 메인 메뉴를 찾지 못했습니다.")
                errors[key] = "메인 메뉴를 찾지 못했습니다."

            # 특수문자 제거 (이미 모델에서 처리하도록 했지만 한번 더 정제)
            refined_menus = [re.sub(r'[\*]+(?=[\uAC00-\uD7A3])', '', menu) for menu in main_menus]
            result_dict[key] = refined_menus

        except Exception as e:
            logger.error(f"메뉴 '{key}' 처리 중 오류 발생: {str(e)}", exc_info=True)
            errors[key] = str(e)
            result_dict[key] = []  # 오류 발생 시 빈 목록 반환

    # 성공 여부 확인
    is_successful = len(errors) == 0

    parsed_menu_data = ParsedMenuData(
        date=today_raw_menu.date,
        restaurant=today_raw_menu.restaurant,
        menus=result_dict,
        error_slots=errors,
        success=is_successful
    )

    # 결과 로깅
    if is_successful:
        logger.info(f"{today_raw_menu.date} {today_raw_menu.restaurant} 메뉴 파싱 성공")
    else:
        error_slots = ", ".join(errors.keys())
        logger.warning(f"{today_raw_menu.date} {today_raw_menu.restaurant} 메뉴 파싱 부분 실패 (슬롯: {error_slots})")

    return parsed_menu_data

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


def check_for_holidays(response: requests.Response, date: str):
    soup = BeautifulSoup(response.text, "html.parser")
    if soup.find(text="오늘은 쉽니다.") or "휴무" in soup.text:
        raise Exception(f"해당 날짜({date})는  휴무일입니다.")


def create_github_summary(results: List[ParsedMenuData]):
    """
    크롤링 결과를 GitHub Actions Summary로 출력합니다.
    """
    summary_md = "# 🍽️ 크롤링 결과\n\n"
    summary_md += f"실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    dates = sorted(set(r.date for r in results))

    success_count = sum(1 for r in results if r.success)
    error_count = sum(1 for r in results if not r.success)

    summary_md += "## 📊 요약\n"
    summary_md += f"- 총 처리 항목: {len(results)}개\n"
    summary_md += f"- 성공: {success_count}개\n"
    summary_md += f"- 실패: {error_count}개\n\n"

    for date in dates:
        date_results = [r for r in results if r.date == date]
        date_success = sum(1 for r in date_results if r.success)

        summary_md += f"## 📅 {date} (성공: {date_success}/{len(date_results)})\n\n"
        summary_md += "| 식당 구분 | 상태 | 메뉴 |\n"
        summary_md += "|:---------|:-----|:----|\n"

        for result in date_results:
            restaurant = result.restaurant  # RestaurantType이라고 가정

            if result.success:
                status = "✅ 성공"
            else:
                errors = ", ".join(
                    f"{slot}: {msg}" for slot, msg in result.error_slots.items()
                ) if result.error_slots else "알 수 없음"
                status = f"❌ 실패 ({errors})"

            menu_items = [
                f"{slot}: {', '.join(items)}"
                for slot, items in result.menus.items()
                if items
            ]
            menu_text = " | ".join(menu_items) if menu_items else "-"

            summary_md += f"| {restaurant} | {status} | {menu_text} |\n"

        summary_md += "\n"

    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary_md)
    else:
        logger.info(summary_md)

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def send_slack_message(parsed_menu_data:ParsedMenuData):
    payload = {
        "channel": "#api-notification",
        "username": "학식봇",
        "text": f"{parsed_menu_data.restaurant}식당({parsed_menu_data.date})의 식단 {parsed_menu_data.menus}\n성공 여부: {parsed_menu_data.success}, 에러 {parsed_menu_data.error_slots}",
        "icon_emoji": ":ghost:"
    }
    headers = {'Content-Type': 'application/json'}

    import json
    response = requests.post(
        SLACK_WEBHOOK_URL,
        data=json.dumps(payload),
        headers=headers,
        timeout=10
    )

    response.raise_for_status()  # HTTP 오류 발생 시 예외 발생
    return response.text
