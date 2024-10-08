from dataclasses import dataclass, field
from typing import List
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from pytz import timezone


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


@dataclass
class RequestBody:
    price: int
    menuNames: List[str] = field(default_factory=list)


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



def get_next_weekdays():
    seoul_tz = timezone("Asia/Seoul")
    current_date = datetime.now().astimezone(seoul_tz)

    # 현재 요일이 월요일이면 7을, 그렇지 않으면 다음 주 월요일까지의 날짜 계산
    weekday = current_date.weekday()
    days_until_monday = 7 if weekday == 0 else (7 - weekday)
    next_monday = current_date + timedelta(days=days_until_monday)

    # 다음 주 금요일까지의 날짜 계산
    next_friday = next_monday + timedelta(days=4)

    # 날짜 범위 내의 날짜를 생성하여 리스트에 추가
    date_list = [next_monday + timedelta(days=i) for i in range(5)]
    date_list_formatted = [date.strftime("%Y%m%d") for date in date_list]

    return date_list_formatted

def get_current_weekdays():
    # 해당하는 날짜를 받으면 그 주의 월요일부터 금요일까지의 날짜를 반환
    seoul_tz = timezone("Asia/Seoul")
    current_date = datetime.today().astimezone(seoul_tz)

    # 해당 주 월요일까지의 날짜 계산
    days_until_monday = current_date.weekday()
    current_monday = current_date - timedelta(days=days_until_monday)

    # 해당 주 금요일까지의 날짜 계산
    days_until_friday = 4  # 해당 주 금요일까지는 4일 필요
    current_friday = current_monday + timedelta(days=days_until_friday)

    # 날짜 범위 내의 날짜를 생성하여 리스트에 추가
    date_list = []

    for i in range(5):  # 월요일부터 금요일까지 5일
        date_list.append(current_monday.strftime("%Y%m%d"))
        current_monday += timedelta(days=1)
    return date_list

def check_for_holidays(response:requests.Response, date:str):
    soup = BeautifulSoup(response.text, "html.parser")
    if soup.find(text="오늘은 쉽니다.") or "휴무" in soup.text:
        raise Exception(f"해당 날짜({date})는  휴무일입니다.")

