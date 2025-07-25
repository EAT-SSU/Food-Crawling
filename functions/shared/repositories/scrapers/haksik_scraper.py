import logging

import aiohttp
from bs4 import BeautifulSoup

from functions.shared.models.exceptions import HolidayException, MenuFetchException
from functions.shared.models.model import RawMenuData, RestaurantType
from functions.shared.repositories.interfaces import MenuScraperInterface
from functions.shared.utils.parsing_utils import parse_table_to_dict, strip_string_from_html

logger = logging.getLogger(__name__)


class HaksikScraper(MenuScraperInterface):
    """학생식당 웹 스크래퍼"""

    def __init__(self, settings=None):
        if settings is None:
            from functions.config.settings import get_settings
            settings = get_settings()

        self.base_url = settings.SOONGGURI_BASE_URL
        self.restaurant_code = settings.SOONGGURI_HAKSIK_RCD

    async def scrape_menu(self, date: str) -> RawMenuData:
        """학생식당 메뉴를 스크래핑합니다."""
        logger.info(f"학생식당 메뉴 스크래핑 시작: {date}")

        url = f"{self.base_url}?rcd={self.restaurant_code}&sdt={date}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                html_content = await response.text()

        # 휴무일 체크
        self._check_for_holidays(html_content, date)

        # 메뉴 파싱
        raw_menu_data = self._parse_menu_from_html(html_content, date)

        logger.info(f"학생식당 메뉴 스크래핑 완료: {date}")
        return raw_menu_data

    def _check_for_holidays(self, html_content: str, date: str) -> None:
        """휴무일 체크"""
        soup = BeautifulSoup(html_content, "html.parser")
        if soup.find(text="오늘은 쉽니다.") or "휴무" in soup.text:
            raise HolidayException(target_date=date, raw_data=html_content)

    def _parse_menu_from_html(self, html_content: str, date: str) -> RawMenuData:
        """HTML에서 메뉴 데이터를 파싱합니다."""
        menu_dict = parse_table_to_dict(html_content)
        stripped_menu_dict = strip_string_from_html(menu_dict)

        raw_menu_data = RawMenuData(
            date=date,
            restaurant=RestaurantType.HAKSIK,
            menu_texts=stripped_menu_dict
        )

        if not raw_menu_data.menu_texts:
            raise MenuFetchException(target_date=date, raw_data=raw_menu_data)

        return raw_menu_data
