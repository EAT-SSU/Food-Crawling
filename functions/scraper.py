from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp
from bs4 import BeautifulSoup, Tag


SOONGGURI_BASE_URL = "http://m.soongguri.com/m_req/m_menu.php"
DORMITORY_BASE_URL = "https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php"

SOONGGURI_RESTAURANTS: Mapping[str, int] = {
    "HAKSIK": 1,
    "DODAM": 2,
    "FACULTY": 7,
}

SUCCESS = "SUCCESS"
EXPECTED_EMPTY = "EXPECTED_EMPTY"
AMBIGUOUS_EMPTY = "AMBIGUOUS_EMPTY"
API_FAILURE = "API_FAILURE"

_CLOSURE_MARKERS = frozenset(
    {
        "휴무",
        "미운영",
        "운영하지 않음",
        "운영하지 않습니다",
        "운영하지 않습니다.",
        "오늘은 쉽니다.",
    }
)
_ENGLISH_PHRASE = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z][A-Za-z'’-]*)(?:[ \t]+[A-Za-z][A-Za-z'’-]*)*"
)


@dataclass(frozen=True)
class MealRecord:
    date: str
    restaurant: str
    source_slot: str
    raw_text: str
    source_english: tuple[str, ...] = ()
    outcome: str = SUCCESS
    reason_code: str = "SOURCE_AVAILABLE"

    @property
    def source_english_evidence(self) -> tuple[str, ...]:
        return self.source_english


class ScraperError(RuntimeError):
    date: str
    restaurant: str
    reason_code: str
    outcome: str
    error_type: str | None
    status: int | None

    def __init__(
        self,
        date: str,
        restaurant: str,
        reason_code: str,
        outcome: str,
        *,
        error_type: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.date = date
        self.restaurant = restaurant
        self.reason_code = reason_code
        self.outcome = outcome
        self.error_type = error_type
        self.status = status


class HolidayError(ScraperError):
    def __init__(self, date: str, restaurant: str) -> None:
        super().__init__(date, restaurant, "HOLIDAY", EXPECTED_EMPTY)


class SourceParseError(ScraperError):
    def __init__(self, date: str, restaurant: str, reason_code: str) -> None:
        super().__init__(date, restaurant, reason_code, AMBIGUOUS_EMPTY)


def _restaurant_name(restaurant: object) -> str:
    value = restaurant if isinstance(restaurant, str) else getattr(restaurant, "name", None)
    if not isinstance(value, str):
        raise ValueError("restaurant must be a restaurant name")
    name = value.upper()
    if name not in {*SOONGGURI_RESTAURANTS, "DORMITORY"}:
        raise ValueError(f"unsupported restaurant: {value}")
    return name


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _is_closure(value: str) -> bool:
    return _normalized_text(value) in _CLOSURE_MARKERS


def _is_day_closure(soup: BeautifulSoup) -> bool:
    for text_node in soup.find_all(
        string=lambda value: bool(value and value.strip() == "오늘은 쉽니다.")
    ):
        parent = text_node.parent
        if not isinstance(parent, Tag):
            continue
        row = parent.find_parent("tr")
        if not isinstance(row, Tag) or row.find("td", class_="menu_nm") is None:
            return True
    return False


def _english_evidence(cells: Sequence[Tag]) -> tuple[str, ...]:
    evidence: list[str] = []
    for cell in cells:
        text = cell.get_text(" ", strip=True)
        for match in _ENGLISH_PHRASE.finditer(text):
            phrase = match.group(0)
            if phrase not in evidence:
                evidence.append(phrase)
    return tuple(evidence)


def parse_soongguri_html(
    html_content: str,
    date: str,
    restaurant: object,
) -> list[MealRecord]:
    name = _restaurant_name(restaurant)
    if name not in SOONGGURI_RESTAURANTS:
        raise ValueError(f"not a Soongguri restaurant: {name}")

    soup = BeautifulSoup(html_content, "html.parser")
    if _is_day_closure(soup):
        raise HolidayError(date, name)

    rows = [
        row
        for row in soup.find_all("tr")
        if isinstance(row, Tag) and row.find("td", class_="menu_nm") is not None
    ]
    if not rows:
        reason = "SOURCE_SCHEMA_CHANGED" if soup.get_text(" ", strip=True) else "SOURCE_EMPTY"
        raise SourceParseError(date, name, reason)

    records: list[MealRecord] = []
    for row in rows:
        slot_cell = row.find("td", class_="menu_nm")
        if not isinstance(slot_cell, Tag):
            continue
        slot = slot_cell.get_text(" ", strip=True)
        source_cells = [
            cell
            for cell in row.find_all("td", recursive=False)
            if isinstance(cell, Tag) and cell is not slot_cell
        ]
        source_texts = [
            cell.get_text(" ", strip=True)
            for cell in source_cells
            if cell.get_text(" ", strip=True)
        ]
        if not source_texts:
            records.append(
                MealRecord(
                    date,
                    name,
                    slot,
                    "",
                    outcome=AMBIGUOUS_EMPTY,
                    reason_code="SOURCE_EMPTY",
                )
            )
        elif all(_is_closure(text) for text in source_texts):
            records.append(
                MealRecord(
                    date,
                    name,
                    slot,
                    " ".join(source_texts),
                    outcome=EXPECTED_EMPTY,
                    reason_code="CLOSED_MARKER",
                )
            )
        else:
            records.append(
                MealRecord(
                    date,
                    name,
                    slot,
                    " ".join(row.stripped_strings),
                    _english_evidence(source_cells),
                )
            )

    if not any(record.outcome == SUCCESS for record in records) and not all(
        record.outcome == EXPECTED_EMPTY for record in records
    ):
        raise SourceParseError(date, name, "SOURCE_EMPTY")
    return records


def _span(cell: Tag, attribute: str) -> int:
    raw_value = cell.get(attribute, "1")
    if not isinstance(raw_value, str) or not raw_value.isdigit() or int(raw_value) < 1:
        raise ValueError(f"invalid {attribute}")
    return int(raw_value)


def _table_matrix(table: Tag) -> list[list[str | None]]:
    rows = [row for row in table.find_all("tr") if isinstance(row, Tag)]
    matrix: list[dict[int, str]] = []
    active: dict[int, tuple[int, str]] = {}

    for row in rows:
        values = {column: value for column, (_, value) in active.items()}
        next_active: dict[int, tuple[int, str]] = {
            column: (remaining - 1, value)
            for column, (remaining, value) in active.items()
            if remaining > 1
        }
        column = 0
        cells = [
            cell
            for cell in row.find_all(["th", "td"], recursive=False)
            if isinstance(cell, Tag)
        ]
        for cell in cells:
            while column in values:
                column += 1
            colspan = _span(cell, "colspan")
            rowspan = _span(cell, "rowspan")
            text = cell.get_text().strip()
            for offset in range(colspan):
                target = column + offset
                if target in values:
                    raise ValueError("overlapping table span")
                values[target] = text
                if rowspan > 1:
                    next_active[target] = (rowspan - 1, text)
            column += colspan
        matrix.append(values)
        active = next_active

    if active:
        raise ValueError("rowspan exceeds table rows")
    if not matrix:
        return []
    width = max((max(row, default=-1) for row in matrix), default=-1) + 1
    return [[row.get(column) for column in range(width)] for row in matrix]


def _requested_date_map(requested_dates: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    ordered = list(dict.fromkeys(requested_dates))
    if not ordered:
        raise ValueError("requested_dates must not be empty")
    by_month_day: dict[str, str] = {}
    for requested in ordered:
        _ = datetime.strptime(requested, "%Y%m%d")
        month_day = requested[4:]
        if month_day in by_month_day and by_month_day[month_day] != requested:
            raise ValueError("requested dates contain an ambiguous month/day")
        by_month_day[month_day] = requested
    return ordered, by_month_day


def _source_date(raw_date: str, requested: Mapping[str, str]) -> str | None:
    clean_date = raw_date.split()[0].replace("-", "")
    if len(clean_date) == 8:
        try:
            _ = datetime.strptime(clean_date, "%Y%m%d")
        except ValueError:
            return None
        return clean_date if clean_date in requested.values() else None
    if len(clean_date) == 4:
        return requested.get(clean_date)
    return None


def parse_dormitory_html(
    html_content: str,
    requested_dates: Iterable[str],
) -> list[MealRecord]:
    ordered_dates, requested = _requested_date_map(requested_dates)
    error_date = ordered_dates[0]
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table", class_="boxstyle02")
    if not isinstance(table, Tag):
        raise SourceParseError(error_date, "DORMITORY", "SOURCE_SCHEMA_CHANGED")

    try:
        matrix = _table_matrix(table)
    except ValueError as error:
        raise SourceParseError(error_date, "DORMITORY", "SOURCE_SCHEMA_CHANGED") from error
    if not matrix:
        raise SourceParseError(error_date, "DORMITORY", "SOURCE_EMPTY")

    headers = matrix[0]
    if "날짜" not in headers:
        raise SourceParseError(error_date, "DORMITORY", "MISSING_DATE_HEADER")
    date_index = headers.index("날짜")
    meal_indices = {
        slot: headers.index(slot) for slot in ("중식", "석식") if slot in headers
    }

    records_by_date: dict[str, list[MealRecord]] = {}
    for row in matrix[1:]:
        raw_date = row[date_index] if date_index < len(row) else None
        if raw_date is None:
            raise SourceParseError(error_date, "DORMITORY", "MISSING_DATE_CELL")
        date = _source_date(raw_date, requested)
        if date is None:
            continue

        day_records: list[MealRecord] = []
        for slot in ("중식", "석식"):
            index = meal_indices.get(slot)
            value = row[index] if index is not None and index < len(row) else None
            if index is None or value is None:
                day_records.append(
                    MealRecord(
                        date,
                        "DORMITORY",
                        slot,
                        "",
                        outcome=AMBIGUOUS_EMPTY,
                        reason_code="MISSING_SLOT_COLUMN",
                    )
                )
                continue

            items = [item.strip() for item in value.split("\r\n") if item.strip()]
            if not items:
                day_records.append(
                    MealRecord(
                        date,
                        "DORMITORY",
                        slot,
                        "",
                        outcome=AMBIGUOUS_EMPTY,
                        reason_code="EMPTY_CELL",
                    )
                )
            elif any(_is_closure(item) for item in items):
                day_records.append(
                    MealRecord(
                        date,
                        "DORMITORY",
                        slot,
                        " ".join(items),
                        outcome=EXPECTED_EMPTY,
                        reason_code="CLOSED_MARKER",
                    )
                )
            else:
                day_records.append(
                    MealRecord(date, "DORMITORY", slot, " ".join(items))
                )
        records_by_date[date] = day_records

    return [record for date in ordered_dates for record in records_by_date.get(date, [])]


def parse_menu_html(
    html_content: str,
    restaurant: object,
    requested_dates: Iterable[str],
) -> list[MealRecord]:
    name = _restaurant_name(restaurant)
    dates = tuple(requested_dates)
    if not dates:
        raise ValueError("requested_dates must not be empty")
    parser = PARSERS[name]
    if name == "DORMITORY":
        return parser(html_content, dates)
    if len(dates) != 1:
        raise ValueError("Soongguri parsing requires exactly one requested date")
    return parser(html_content, dates[0], name)


PARSERS: Mapping[str, Callable[..., list[MealRecord]]] = {
    "HAKSIK": parse_soongguri_html,
    "DODAM": parse_soongguri_html,
    "FACULTY": parse_soongguri_html,
    "DORMITORY": parse_dormitory_html,
}


async def fetch_meals(
    restaurant: object,
    date: str,
    *,
    requested_dates: Iterable[str] | None = None,
    soongguri_base_url: str = SOONGGURI_BASE_URL,
    dormitory_base_url: str = DORMITORY_BASE_URL,
    session_factory: Callable[[], Any] | None = None,
) -> list[MealRecord]:
    name = _restaurant_name(restaurant)
    dates = tuple(requested_dates) if requested_dates is not None else (date,)
    make_session = session_factory or aiohttp.ClientSession

    try:
        async with make_session() as session:
            if name == "DORMITORY":
                date_value = datetime.strptime(date, "%Y%m%d")
                params = {
                    "viewform": "B0001_foodboard_list",
                    "gyear": date_value.year,
                    "gmonth": date_value.month,
                    "gday": date_value.day,
                }
                request = session.get(dormitory_base_url, params=params)
            else:
                url = f"{soongguri_base_url}?rcd={SOONGGURI_RESTAURANTS[name]}&sdt={date}"
                request = session.get(url)
            async with request as response:
                _ = response.raise_for_status()
                html_content = await response.text()
    except Exception as error:
        status_value = getattr(error, "status", None)
        status = status_value if isinstance(status_value, int) else None
        raise ScraperError(
            date,
            name,
            "SOURCE_HTTP_ERROR",
            API_FAILURE,
            error_type=type(error).__name__,
            status=status,
        ) from None

    return parse_menu_html(html_content, name, dates)
