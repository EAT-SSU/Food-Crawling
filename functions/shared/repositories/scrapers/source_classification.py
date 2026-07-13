from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Tag

from functions.shared.models.exceptions import MenuFetchException
from functions.shared.models.model import (
    ProcessingOutcome,
    RawMenuData,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import emit_event, fingerprint_source


SOURCE_STAGE = "source_parse"
EXPLICIT_SLOT_CLOSURE_MARKERS = frozenset(
    {
        "휴무",
        "미운영",
        "운영하지 않음",
        "운영하지 않습니다",
        "운영하지 않습니다.",
        "오늘은 쉽니다.",
    }
)


def make_source_result(
    slot: str,
    outcome: ProcessingOutcome,
    reason_code: str,
    source: Optional[str] = None,
    *,
    stage: str = SOURCE_STAGE,
    error_type: Optional[str] = None,
) -> SlotProcessingResult:
    source_length = None
    source_sha256 = None
    if source is not None:
        source_length, source_sha256 = fingerprint_source(source)
    return SlotProcessingResult(
        slot=slot,
        stage=stage,
        outcome=outcome,
        reason_code=reason_code,
        source_length=source_length,
        source_sha256=source_sha256,
        error_type=error_type,
    )


def emit_source_result(
    result: SlotProcessingResult,
    date: str,
    restaurant: RestaurantType,
    *,
    event_name: str = "source_classified",
    status: Optional[int] = None,
) -> None:
    emit_event(
        "INFO" if result.outcome == ProcessingOutcome.SUCCESS else "WARNING",
        event_name,
        result.stage,
        restaurant=restaurant.english_name,
        date=date,
        slot=result.slot,
        outcome=result.outcome,
        reason_code=result.reason_code,
        source_length=result.source_length,
        source_sha256=result.source_sha256,
        status=status,
        **{"error.type": result.error_type},
    )


def is_explicit_day_closure(html_content: str) -> bool:
    soup = BeautifulSoup(html_content, "html.parser")
    for text_node in soup.find_all(string=lambda value: bool(value and value.strip() == "오늘은 쉽니다.")):
        parent = text_node.parent
        if not isinstance(parent, Tag):
            continue
        row = parent.find_parent("tr")
        if not isinstance(row, Tag) or row.find("td", class_="menu_nm") is None:
            return True
    return False


def is_explicit_slot_closure(text: str) -> bool:
    normalized = " ".join(text.split())
    return normalized in EXPLICIT_SLOT_CLOSURE_MARKERS


def classify_general_source(
    html_content: str,
    date: str,
    restaurant: RestaurantType,
) -> RawMenuData:
    soup = BeautifulSoup(html_content, "html.parser")
    menu_texts: Dict[str, str] = {}
    slot_results: Dict[str, SlotProcessingResult] = {}

    rows: List[Tag] = []
    for candidate in soup.find_all("tr"):
        if isinstance(candidate, Tag) and candidate.find("td", class_="menu_nm") is not None:
            rows.append(candidate)
    if not rows:
        has_visible_source = bool(soup.get_text(" ", strip=True))
        reason_code = "SOURCE_SCHEMA_CHANGED" if has_visible_source else "SOURCE_EMPTY"
        result = make_source_result(
            "__source__",
            ProcessingOutcome.AMBIGUOUS_EMPTY,
            reason_code,
            html_content,
        )
        emit_source_result(result, date, restaurant)
        raw_data = RawMenuData(date, restaurant, {}, {"__source__": result})
        raise MenuFetchException(
            date,
            restaurant,
            raw_data,
            reason_code=reason_code,
            outcome=ProcessingOutcome.AMBIGUOUS_EMPTY,
        )

    for row in rows:
        slot_cell = row.find("td", class_="menu_nm")
        if not isinstance(slot_cell, Tag):
            continue
        slot = slot_cell.get_text(" ", strip=True)
        source_cells = [cell for cell in row.find_all("td") if cell is not slot_cell]
        source_texts = [
            cell.get_text(" ", strip=True)
            for cell in source_cells
            if cell.get_text(" ", strip=True)
        ]
        if not source_texts:
            result = make_source_result(
                slot,
                ProcessingOutcome.AMBIGUOUS_EMPTY,
                "SOURCE_EMPTY",
                "",
            )
        elif all(is_explicit_slot_closure(text) for text in source_texts):
            result = make_source_result(
                slot,
                ProcessingOutcome.EXPECTED_EMPTY,
                "CLOSED_MARKER",
                " ".join(source_texts),
            )
        else:
            menu_text = " ".join(row.stripped_strings)
            menu_texts[slot] = menu_text
            result = make_source_result(
                slot,
                ProcessingOutcome.SUCCESS,
                "SOURCE_AVAILABLE",
                menu_text,
            )
        slot_results[slot] = result
        emit_source_result(result, date, restaurant)

    raw_data = RawMenuData(date, restaurant, menu_texts, slot_results)
    if not menu_texts and not all(
        result.outcome == ProcessingOutcome.EXPECTED_EMPTY
        for result in slot_results.values()
    ):
        raise MenuFetchException(
            date,
            restaurant,
            raw_data,
            outcome=ProcessingOutcome.AMBIGUOUS_EMPTY,
        )
    return raw_data


def record_fetch_failure(
    error: BaseException,
    date: str,
    restaurant: RestaurantType,
) -> MenuFetchException:
    status_value = getattr(error, "status", None)
    status = status_value if isinstance(status_value, int) else None
    result = make_source_result(
        "__source__",
        ProcessingOutcome.API_FAILURE,
        "SOURCE_HTTP_ERROR",
        stage="source_fetch",
        error_type=type(error).__name__,
    )
    emit_source_result(result, date, restaurant, event_name="source_fetch_failed", status=status)
    return MenuFetchException(
        date,
        restaurant,
        reason_code="SOURCE_HTTP_ERROR",
        outcome=ProcessingOutcome.API_FAILURE,
        error_type=type(error).__name__,
        status=status,
    )
