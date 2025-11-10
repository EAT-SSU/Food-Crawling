import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Tuple

import aiohttp
from bs4 import BeautifulSoup

from functions.shared.models.exceptions import MenuFetchException
from functions.shared.models.model import RawMenuData, RestaurantType
from functions.shared.repositories.interfaces import MenuScraperInterface
from functions.shared.utils.parsing_utils import make2d

logger = logging.getLogger(__name__)


class DormitoryScraper(MenuScraperInterface):
    """기숙사식당 웹 스크래퍼 - 간결한 버전"""

    def __init__(self, settings=None):
        if settings is None:
            from functions.config.settings import get_settings
            settings = get_settings()
        self.base_url = settings.DORMITORY_BASE_URL

    async def scrape_menu(self, date: str) -> List[RawMenuData]:
        """기숙사식당 주간 메뉴를 스크래핑합니다"""
        logger.info(f"기숙사식당 주간 메뉴 스크래핑 시작: {date}")

        # HTML 콘텐츠 가져오기
        try:
            html_content = await self._fetch_menu_html(date)

            # HTML 파싱하여 메뉴 데이터 추출
            raw_menu_list = self._parse_html_to_raw_menu_data(html_content)[:7] # TODO: 추후 주말 기숙사 식당 추가 시 슬라이싱 제거 제거하는 거랑 관계 없이 여기서 이렇게 하면 안되는데...
            logger.info(f"기숙사식당 주간 메뉴 스크래핑 완료: {len(raw_menu_list)}일치")
        except Exception as e:
            menu_fetch_exception = MenuFetchException(
                target_date=date,
                restaurant_type=RestaurantType.DORMITORY,
            )
            menu_fetch_exception.add_note(str(e))
            raise menu_fetch_exception
        return raw_menu_list

    async def _fetch_menu_html(self, date: str) -> str:
        """주어진 날짜로 메뉴 HTML을 가져옵니다"""
        date_obj = datetime.strptime(date, '%Y%m%d')
        params = {
            'viewform': 'B0001_foodboard_list',
            'gyear': date_obj.year,
            'gmonth': date_obj.month,
            'gday': date_obj.day
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as response:
                response.raise_for_status()
                return await response.text()

    def _parse_html_to_raw_menu_data(self, html_content: str) -> List[RawMenuData]:
        """HTML을 파싱하여 RawMenuData 리스트로 변환"""
        # HTML에서 테이블 추출
        table_data = self._extract_table_from_html(html_content)

        # 테이블 데이터를 구조화된 형태로 변환
        structured_data = self._structure_table_data(table_data)

        # 구조화된 데이터를 RawMenuData로 변환
        return self._convert_to_raw_menu_data(structured_data)

    def _extract_table_from_html(self, html_content: str) -> List[List[str]]:
        """HTML에서 테이블을 추출하여 2D 리스트로 반환"""
        soup = BeautifulSoup(html_content, 'html.parser')
        table_tag = soup.find("table", "boxstyle02")
        table_data = make2d(table_tag)

        return table_data

    def _structure_table_data(self, table_data: List[List[str]]) -> List[Dict[str, any]]:
        """2D 테이블 데이터를 구조화된 딕셔너리 리스트로 변환"""
        if not table_data:
            return []

        # 헤더와 컬럼 인덱스 매핑
        headers = table_data[0]
        date_col_idx, meal_col_indices = self._get_column_indices(headers)

        # 각 행을 딕셔너리로 변환
        structured_data = []
        for row in table_data[1:]:  # 헤더 제외
            if len(row) > date_col_idx:
                row_data = self._process_table_row(row, date_col_idx, meal_col_indices)
                structured_data.append(row_data)

        return structured_data

    def _get_column_indices(self, headers: List[str]) -> Tuple[int, Dict[str, int]]:
        """헤더에서 날짜와 식사 시간 컬럼의 인덱스를 찾습니다"""
        date_col_idx = None
        meal_col_indices = {}

        for i, header in enumerate(headers):
            if header == '날짜':
                date_col_idx = i
            elif header in ['조식', '중식', '석식']:
                meal_col_indices[header] = i

        return date_col_idx, meal_col_indices

    def _process_table_row(self, row: List[str], date_col_idx: int, meal_col_indices: Dict[str, int]) -> Dict[str, any]:
        """테이블 행을 처리하여 구조화된 데이터로 변환"""
        row_data = {'날짜': row[date_col_idx]}

        # 각 식사 시간 데이터 추가
        for meal_time, col_idx in meal_col_indices.items():
            if col_idx < len(row):
                menu_text = row[col_idx] if row[col_idx] else ""
                row_data[meal_time] = menu_text.split("\r\n") if menu_text else []

        return row_data

    def _convert_to_raw_menu_data(self, structured_data: List[Dict[str, any]]) -> List[RawMenuData]:
        """구조화된 데이터를 RawMenuData 리스트로 변환"""
        raw_menu_list = []

        for row_data in structured_data:
            # 날짜 파싱
            date_str = self._parse_date(str(row_data['날짜']))
            if not date_str:
                continue

            # 메뉴 텍스트 구성 (조식은 스크래핑하되 제외)
            menu_texts = self._extract_menu_texts(row_data)

            # 메뉴가 있는 경우에만 RawMenuData 생성
            if menu_texts:
                raw_menu_list.append(RawMenuData(
                    date=date_str,
                    restaurant=RestaurantType.DORMITORY,
                    menu_texts=menu_texts
                ))

        return raw_menu_list

    def _extract_menu_texts(self, row_data: Dict[str, any]) -> Dict[str, str]:
        """행 데이터에서 메뉴 텍스트를 추출합니다 (조식 제외)"""
        menu_texts = {}

        for meal_time in ['중식', '석식']:  # 조식 제외
            if meal_time in row_data:
                menu_list = row_data[meal_time]
                if isinstance(menu_list, list):
                    # 빈 값 제거 및 운영 체크
                    cleaned_items = [item.strip() for item in menu_list if item.strip()]
                    if cleaned_items and not any("운영" in item for item in cleaned_items):
                        menu_texts[meal_time] = " ".join(cleaned_items)

        return menu_texts

    def _parse_date(self, date_str: str) -> str:
        """날짜 문자열을 YYYYMMDD 형식으로 변환"""
        try:
            # "2024-03-25" 또는 "03-25" 형식 처리
            clean_date = date_str.split()[0].replace("-", "")
            if len(clean_date) == 4:  # MM-DD 형태
                current_year = datetime.now().year
                clean_date = f"{current_year}{clean_date}"
            return clean_date if len(clean_date) == 8 else ""
        except:
            return ""


if __name__ == '__main__':
    d = DormitoryScraper()
    menus = asyncio.run(d.scrape_menu('20250731'))