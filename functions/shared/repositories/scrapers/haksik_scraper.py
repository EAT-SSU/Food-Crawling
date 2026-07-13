import aiohttp

from functions.shared.models.exceptions import HolidayException
from functions.shared.models.model import ProcessingOutcome, RawMenuData, RestaurantType
from functions.shared.repositories.interfaces import MenuScraperInterface
from functions.shared.repositories.scrapers.source_classification import (
    classify_general_source,
    emit_source_result,
    is_explicit_day_closure,
    make_source_result,
    record_fetch_failure,
)


class HaksikScraper(MenuScraperInterface):
    """학생식당 웹 스크래퍼"""

    def __init__(self, settings=None):
        if settings is None:
            from functions.config.settings import get_settings
            settings = get_settings()
        self.base_url = settings.SOONGGURI_BASE_URL
        self.restaurant_code = settings.SOONGGURI_HAKSIK_RCD

    async def scrape_menu(self, date: str) -> RawMenuData:
        url = f"{self.base_url}?rcd={self.restaurant_code}&sdt={date}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    html_content = await response.text()
        except Exception as error:
            raise record_fetch_failure(error, date, RestaurantType.HAKSIK) from None

        self._check_for_holidays(html_content, date)
        return self._parse_menu_from_html(html_content, date)

    def _check_for_holidays(self, html_content: str, date: str) -> None:
        if is_explicit_day_closure(html_content):
            result = make_source_result(
                "__day__", ProcessingOutcome.EXPECTED_EMPTY, "HOLIDAY", html_content
            )
            emit_source_result(result, date, RestaurantType.HAKSIK)
            raise HolidayException(date, RestaurantType.HAKSIK, html_content)

    def _parse_menu_from_html(self, html_content: str, date: str) -> RawMenuData:
        return classify_general_source(html_content, date, RestaurantType.HAKSIK)
