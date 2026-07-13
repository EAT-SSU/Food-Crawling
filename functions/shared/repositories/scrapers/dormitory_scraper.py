import asyncio
from datetime import datetime
from typing import Any, Dict, List, Tuple

import aiohttp
from bs4 import BeautifulSoup

from functions.shared.models.exceptions import MenuFetchException
from functions.shared.models.model import ProcessingOutcome, RawMenuData, RestaurantType, SlotProcessingResult
from functions.shared.repositories.interfaces import MenuScraperInterface
from functions.shared.repositories.scrapers.source_classification import (
    emit_source_result,
    is_explicit_slot_closure,
    make_source_result,
    record_fetch_failure,
)
from functions.shared.utils.parsing_utils import make2d


class DormitoryScraper(MenuScraperInterface):
    """기숙사식당 웹 스크래퍼 - 간결한 버전"""

    def __init__(self, settings=None):
        if settings is None:
            from functions.config.settings import get_settings
            settings = get_settings()
        self.base_url = settings.DORMITORY_BASE_URL

    async def scrape_menu(self, date: str) -> List[RawMenuData]:
        try:
            html_content = await self._fetch_menu_html(date)
        except Exception as error:
            raise record_fetch_failure(error, date, RestaurantType.DORMITORY) from None

        try:
            base_year = datetime.strptime(date, "%Y%m%d").year
            return self._parse_html_to_raw_menu_data(html_content, base_year)[:7]  # TODO: 추후 주말 기숙사 식당 추가 시 슬라이싱 제거 제거하는 거랑 관계 없이 여기서 이렇게 하면 안되는데...
        except MenuFetchException:
            raise
        except Exception as error:
            result = make_source_result(
                "__source__",
                ProcessingOutcome.AMBIGUOUS_EMPTY,
                "SOURCE_SCHEMA_CHANGED",
                error_type=type(error).__name__,
            )
            emit_source_result(result, date, RestaurantType.DORMITORY)
            raise MenuFetchException(
                date,
                RestaurantType.DORMITORY,
                reason_code="SOURCE_SCHEMA_CHANGED",
                outcome=ProcessingOutcome.AMBIGUOUS_EMPTY,
                error_type=type(error).__name__,
            ) from None

    async def _fetch_menu_html(self, date: str) -> str:
        date_obj = datetime.strptime(date, "%Y%m%d")
        params = {
            "viewform": "B0001_foodboard_list",
            "gyear": date_obj.year,
            "gmonth": date_obj.month,
            "gday": date_obj.day,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as response:
                response.raise_for_status()
                return await response.text()

    def _parse_html_to_raw_menu_data(self, html_content: str, base_year: int) -> List[RawMenuData]:
        table_data = self._extract_table_from_html(html_content)
        structured_data = self._structure_table_data(table_data)
        return self._convert_to_raw_menu_data(structured_data, base_year)

    def _extract_table_from_html(self, html_content: str) -> List[List[str]]:
        soup = BeautifulSoup(html_content, "html.parser")
        table_tag = soup.find("table", class_="boxstyle02")
        if table_tag is None:
            raise ValueError("dormitory menu table missing")
        return make2d(table_tag)

    def _structure_table_data(self, table_data: List[List[str]]) -> List[Dict[str, Any]]:
        if not table_data:
            return []
        headers = table_data[0]
        date_col_idx, meal_col_indices = self._get_column_indices(headers)
        structured_data = []
        for row in table_data[1:]:
            if len(row) > date_col_idx:
                structured_data.append(
                    self._process_table_row(row, date_col_idx, meal_col_indices)
                )
        return structured_data

    def _get_column_indices(self, headers: List[str]) -> Tuple[int, Dict[str, int]]:
        date_col_idx = None
        meal_col_indices = {}
        for index, header in enumerate(headers):
            if header == "날짜":
                date_col_idx = index
            elif header in ["조식", "중식", "석식"]:
                meal_col_indices[header] = index
        if date_col_idx is None:
            raise ValueError("dormitory date column missing")
        return date_col_idx, meal_col_indices

    def _process_table_row(
        self,
        row: List[str],
        date_col_idx: int,
        meal_col_indices: Dict[str, int],
    ) -> Dict[str, Any]:
        row_data: Dict[str, Any] = {"날짜": row[date_col_idx]}
        for meal_time, col_idx in meal_col_indices.items():
            if col_idx < len(row):
                menu_text = row[col_idx] if row[col_idx] else ""
                row_data[meal_time] = menu_text.split("\r\n") if menu_text else []
        return row_data

    def _convert_to_raw_menu_data(
        self, structured_data: List[Dict[str, Any]], base_year: int
    ) -> List[RawMenuData]:
        raw_menu_list = []
        for row_data in structured_data:
            raw_date = str(row_data["날짜"])
            date_str = self._parse_date(raw_date, base_year)
            if not date_str:
                result = make_source_result(
                    "__date__",
                    ProcessingOutcome.AMBIGUOUS_EMPTY,
                    "INVALID_DATE",
                    raw_date,
                )
                emit_source_result(
                    result,
                    "unknown",
                    RestaurantType.DORMITORY,
                    event_name="source_date_invalid",
                )
                continue

            menu_texts, slot_results = self._classify_menu_texts(row_data)
            for result in slot_results.values():
                emit_source_result(result, date_str, RestaurantType.DORMITORY)
            raw_menu_list.append(
                RawMenuData(
                    date=date_str,
                    restaurant=RestaurantType.DORMITORY,
                    menu_texts=menu_texts,
                    slot_results=slot_results,
                )
            )
        return raw_menu_list

    def _classify_menu_texts(
        self, row_data: Dict[str, Any]
    ) -> Tuple[Dict[str, str], Dict[str, SlotProcessingResult]]:
        menu_texts: Dict[str, str] = {}
        slot_results: Dict[str, SlotProcessingResult] = {}
        for meal_time in ["중식", "석식"]:
            if meal_time not in row_data:
                result = make_source_result(
                    meal_time,
                    ProcessingOutcome.AMBIGUOUS_EMPTY,
                    "MISSING_SLOT_COLUMN",
                )
            else:
                menu_list = row_data[meal_time]
                cleaned_items = (
                    [item.strip() for item in menu_list if item.strip()]
                    if isinstance(menu_list, list)
                    else []
                )
                if not cleaned_items:
                    result = make_source_result(
                        meal_time,
                        ProcessingOutcome.AMBIGUOUS_EMPTY,
                        "EMPTY_CELL",
                        "",
                    )
                elif any(is_explicit_slot_closure(item) for item in cleaned_items):
                    result = make_source_result(
                        meal_time,
                        ProcessingOutcome.EXPECTED_EMPTY,
                        "CLOSED_MARKER",
                        " ".join(cleaned_items),
                    )
                else:
                    menu_text = " ".join(cleaned_items)
                    menu_texts[meal_time] = menu_text
                    result = make_source_result(
                        meal_time,
                        ProcessingOutcome.SUCCESS,
                        "SOURCE_AVAILABLE",
                        menu_text,
                    )
            slot_results[meal_time] = result
        return menu_texts, slot_results

    def _extract_menu_texts(self, row_data: Dict[str, Any]) -> Dict[str, str]:
        menu_texts, _ = self._classify_menu_texts(row_data)
        return menu_texts

    def _parse_date(self, date_str: str, base_year: int) -> str:
        try:
            clean_date = date_str.split()[0].replace("-", "")
            if len(clean_date) == 4:
                clean_date = f"{base_year}{clean_date}"
            datetime.strptime(clean_date, "%Y%m%d")
            return clean_date
        except (IndexError, ValueError):
            return ""


if __name__ == "__main__":
    d = DormitoryScraper()
    menus = asyncio.run(d.scrape_menu("20250731"))
