# functions/shared/repositories/scrapers/dormitory_scraper.py
import asyncio
import logging
from datetime import datetime
from typing import List

import aiohttp
import pandas as pd
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

        # API 호출
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
                html_content = await response.text()

        # HTML 파싱
        raw_menu_list = self._parse_html_to_raw_menu_data(html_content)

        logger.info(f"기숙사식당 주간 메뉴 스크래핑 완료: {len(raw_menu_list)}일치")
        return raw_menu_list

    def _parse_html_to_raw_menu_data(self, html_content: str) -> List[RawMenuData]:
        """HTML을 파싱하여 RawMenuData 리스트로 변환"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            table_tag = soup.find("table", "boxstyle02")

            if not table_tag:
                raise MenuFetchException(target_date="weekly", raw_data="테이블을 찾을 수 없습니다")

            # 테이블을 DataFrame으로 변환
            table = make2d(table_tag)
            df = pd.DataFrame(table)
            df.columns = df.iloc[0]  # 첫 행을 헤더로
            df = df.drop(df.index[0]).set_index('날짜')

            # 메뉴 텍스트 분리
            for col in ['조식', '중식', '석식']:
                if col in df.columns:
                    df[col] = df[col].str.split("\r\n")

            # 불필요한 컬럼 제거
            if "중.석식" in df.columns:
                del df["중.석식"]

            # 각 날짜별로 RawMenuData 생성
            raw_menu_list = []
            for index, row in df.iterrows():
                # 날짜 파싱
                date_str = self._parse_date(str(index))
                if not date_str:
                    continue

                # 메뉴 텍스트 구성 (조식은 스크래핑하되 제외)
                menu_texts = {}
                for meal_time in ['중식', '석식']:  # 조식 제외
                    if meal_time in df.columns:
                        menu_list = row[meal_time]
                        if isinstance(menu_list, list):
                            # 빈 값 제거 및 운영 체크
                            cleaned_items = [item.strip() for item in menu_list if item.strip()]
                            if cleaned_items and not any("운영" in item for item in cleaned_items):
                                menu_texts[meal_time] = " ".join(cleaned_items)

                # 메뉴가 있는 경우에만 RawMenuData 생성
                if menu_texts:
                    raw_menu_list.append(RawMenuData(
                        date=date_str,
                        restaurant=RestaurantType.DORMITORY,
                        menu_texts=menu_texts
                    ))

            return raw_menu_list

        except Exception as e:
            logger.error(f"기숙사 메뉴 파싱 오류: {e}")
            raise MenuFetchException(target_date="weekly", raw_data=str(e))

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
    menus = asyncio.run(d.scrape_menu('20250721'))