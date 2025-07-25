import logging

import aiohttp
import pandas as pd
from bs4 import BeautifulSoup

from functions.shared.models.exceptions import MenuFetchException
from functions.shared.models.menu import RawMenuData, RestaurantType
from functions.shared.repositories.interfaces import MenuScraperInterface
from functions.shared.utils.parsing_utils import make2d

logger = logging.getLogger(__name__)


class DormitoryScraper(MenuScraperInterface):
    """기숙사식당 웹 스크래퍼"""

    def __init__(self, settings=None):
        if settings is None:
            from functions.config.settings import get_settings
            settings = get_settings()

        self.base_url = settings.DORMITORY_BASE_URL

    async def scrape_menu(self, date: str) -> RawMenuData:
        """기숙사식당 메뉴를 스크래핑합니다 (주간 데이터에서 특정 날짜 추출)."""
        logger.info(f"기숙사식당 메뉴 스크래핑 시작: {date}")

        # 날짜 파싱 (YYYYMMDD → year, month, day)
        year = int(date[:4])
        month = int(date[4:6])
        day = int(date[6:8])

        params = {
            'viewform': 'B0001_foodboard_list',
            'gyear': year,
            'gmonth': month,
            'gday': day
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as response:
                response.raise_for_status()
                html_content = await response.text()

        # 기숙사는 별도 파싱 로직 (주간 데이터에서 해당 날짜만 추출)
        raw_menu_data = self._parse_dormitory_menu(html_content, date)

        logger.info(f"기숙사식당 메뉴 스크래핑 완료: {date}")
        return raw_menu_data

    def _parse_dormitory_menu(self, html_content: str, date: str) -> RawMenuData:
        """기숙사 메뉴 파싱 (기존 Dormitory 클래스 로직 적용)"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            table_tag = soup.find("table", "boxstyle02")

            if not table_tag:
                raise MenuFetchException(target_date=date, raw_data="테이블을 찾을 수 없습니다")

            # 2D 테이블로 변환
            table = make2d(table_tag)
            df = pd.DataFrame(table)

            # 첫 번째 행을 헤더로 사용
            dt2 = df.rename(columns=df.iloc[0])
            dt3 = dt2.drop(dt2.index[0])

            # 메뉴 텍스트 처리 (줄바꿈으로 분리된 메뉴들을 리스트로 변환)
            if "조식" in dt3.columns:
                dt3["조식"] = dt3["조식"].str.split("\r\n").apply(
                    lambda x: [item.strip() for item in x if item.strip()] if isinstance(x, list) else []
                )
            if "중식" in dt3.columns:
                dt3["중식"] = dt3["중식"].str.split("\r\n").apply(
                    lambda x: [item.strip() for item in x if item.strip()] if isinstance(x, list) else []
                )
            if "석식" in dt3.columns:
                dt3["석식"] = dt3["석식"].str.split("\r\n").apply(
                    lambda x: [item.strip() for item in x if item.strip()] if isinstance(x, list) else []
                )

            # 불필요한 컬럼 제거
            if "중.석식" in dt3.columns:
                del dt3["중.석식"]

            dt3 = dt3.set_index('날짜')

            # 해당 날짜의 메뉴만 추출
            target_date_str = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            menu_texts = {}

            for index, row in dt3.iterrows():
                # 날짜 매칭 (여러 형태의 날짜 형식 처리)
                if target_date_str in str(index) or date[4:6] + "-" + date[6:8] in str(index):
                    for meal_time in ['조식', '중식', '석식']:
                        if meal_time in dt3.columns:
                            menu_list = row[meal_time]
                            if isinstance(menu_list, list) and menu_list:
                                # 운영하지 않는 메뉴 체크
                                if not any("운영" in menu for menu in menu_list):
                                    menu_texts[meal_time] = " ".join(menu_list)
                    break

            if not menu_texts:
                raise MenuFetchException(target_date=date, raw_data="해당 날짜의 메뉴를 찾을 수 없습니다")

            return RawMenuData(
                date=date,
                restaurant=RestaurantType.DORMITORY,
                menu_texts=menu_texts
            )

        except Exception as e:
            logger.error(f"기숙사 메뉴 파싱 오류: {e}")
            raise MenuFetchException(target_date=date, raw_data=str(e))
