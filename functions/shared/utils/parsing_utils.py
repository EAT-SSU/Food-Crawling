from typing import Dict, Any

from bs4 import BeautifulSoup


def parse_table_to_dict(html_content: str) -> Dict[str, Any]:
    """HTML 문자열에서 테이블을 파싱하여 딕셔너리로 반환"""
    soup = BeautifulSoup(html_content, "html.parser")
    tr_list = soup.find_all('tr')
    menu_nm_dict = {}

    for tr_tag in tr_list:
        td_tag = tr_tag.find('td', {'class': 'menu_nm'})
        if td_tag:
            menu_nm_dict[td_tag.text] = tr_tag

    return menu_nm_dict


def parse_table_to_dict(html_content: str) -> Dict[str, Any]:
    """HTML 문자열에서 테이블을 파싱하여 딕셔너리로 반환"""
    soup = BeautifulSoup(html_content, "html.parser")
    tr_list = soup.find_all('tr')
    menu_nm_dict = {}

    for tr_tag in tr_list:
        td_tag = tr_tag.find('td', {'class': 'menu_nm'})
        if td_tag:
            menu_nm_dict[td_tag.text] = tr_tag

    return menu_nm_dict


def strip_string_from_html(menu_dict: Dict[str, Any]) -> Dict[str, str]:
    """HTML 요소에서 텍스트를 추출하여 정리"""
    for key, value in menu_dict.items():
        new_text = " ".join(text for text in value.stripped_strings)
        menu_dict[key] = new_text
    return menu_dict


def find_rows(table):
    """테이블에서 모든 행을 찾습니다"""
    return table.find_all('tr')


def find_cells(row):
    """행에서 모든 셀을 찾습니다"""
    cells = []

    ths = row.find_all('th', recursive=False)
    if ths:
        cells.extend(ths)
    tds = row.find_all('td', recursive=False)
    if tds:
        cells.extend(tds)

    return cells


def insert_colspans(twod):
    """colspan 속성을 처리합니다"""
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
    """rowspan 속성을 처리합니다"""
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
    """2D 배열에서 텍스트만 추출합니다"""
    text2d = []

    for rdx, row in enumerate(twod):
        text2d.append([])
        for cell in row:
            text2d[rdx].append(cell.text.strip())

    return text2d


def make2d(table, text_only=True):
    """테이블을 2D 배열로 변환합니다"""
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