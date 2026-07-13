import asyncio
import hashlib
import io
import json
from typing import cast

import aiohttp
import pytest

from functions.shared.models.exceptions import HolidayException, MenuFetchException
from functions.shared.models.model import ProcessingOutcome, RestaurantType
from functions.shared.observability import initialize_observation_logger
from functions.shared.repositories.scrapers.dodam_scraper import DodamScraper
from functions.shared.repositories.scrapers.dormitory_scraper import DormitoryScraper
from functions.shared.repositories.scrapers.faculty_scraper import FacultyScraper
from functions.shared.repositories.scrapers.haksik_scraper import HaksikScraper


DATE = "20260713"
SENTINEL = "<html>SECRET_TOKEN"


class _Settings:
    SOONGGURI_BASE_URL = "https://source.invalid/menu"
    SOONGGURI_DODAM_RCD = "dodam"
    SOONGGURI_HAKSIK_RCD = "haksik"
    SOONGGURI_FACULTY_RCD = "faculty"
    DORMITORY_BASE_URL = "https://source.invalid/dormitory"


@pytest.fixture
def observation_output():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    return output


def _events(output: io.StringIO):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def _general_html(slot: str = "중식1", menu: str = "김치찌개 밥") -> str:
    return (
        "<table><tr>"
        f'<td class="menu_nm">{slot}</td><td>{menu}</td>'
        "</tr></table>"
    )


@pytest.mark.parametrize(
    ("scraper_type", "restaurant"),
    [
        (DodamScraper, RestaurantType.DODAM),
        (HaksikScraper, RestaurantType.HAKSIK),
        (FacultyScraper, RestaurantType.FACULTY),
    ],
)
def test_general_scrapers_classify_normal_nonempty_source(
    scraper_type, restaurant, observation_output
):
    scraper = scraper_type(_Settings())

    raw = scraper._parse_menu_from_html(_general_html(), DATE)

    assert raw.restaurant == restaurant
    assert raw.menu_texts["중식1"] == "중식1 김치찌개 밥"
    result = raw.slot_results["중식1"]
    assert result.outcome == ProcessingOutcome.SUCCESS
    assert result.reason_code == "SOURCE_AVAILABLE"
    assert result.stage == "source_parse"
    assert result.source_length == len(raw.menu_texts["중식1"].encode("utf-8"))
    assert len(result.source_sha256 or "") == 12


def test_explicit_whole_day_holiday_is_expected_empty(observation_output):
    scraper = DodamScraper(_Settings())
    html = "<main><p>오늘은 쉽니다.</p></main>"

    with pytest.raises(HolidayException) as raised:
        scraper._check_for_holidays(html, DATE)

    assert raised.value.reason_code == "HOLIDAY"
    event = _events(observation_output)[-1]
    assert event["outcome"] == "EXPECTED_EMPTY"
    assert event["reason_code"] == "HOLIDAY"
    assert event["stage"] == "source_parse"
    assert html not in observation_output.getvalue()


@pytest.mark.parametrize("closed_marker", ["휴무", "미운영"])
def test_slot_holiday_text_does_not_suppress_valid_peer_slot(
    observation_output, closed_marker
):
    scraper = DodamScraper(_Settings())
    html = (
        "<table>"
        f'<tr><td class="menu_nm">중식1</td><td>{closed_marker}</td></tr>'
        '<tr><td class="menu_nm">석식1</td><td>비빔밥 된장국</td></tr>'
        "</table>"
    )

    scraper._check_for_holidays(html, DATE)
    raw = scraper._parse_menu_from_html(html, DATE)

    assert "중식1" not in raw.menu_texts
    assert raw.slot_results["중식1"].outcome == ProcessingOutcome.EXPECTED_EMPTY
    assert raw.slot_results["중식1"].reason_code == "CLOSED_MARKER"
    assert raw.menu_texts["석식1"] == "석식1 비빔밥 된장국"
    assert raw.slot_results["석식1"].outcome == ProcessingOutcome.SUCCESS


def test_slot_text_merely_containing_operation_word_remains_success(
    observation_output,
):
    scraper = DodamScraper(_Settings())

    raw = scraper._parse_menu_from_html(
        _general_html(menu="정상 운영 특식"), DATE
    )

    assert raw.menu_texts["중식1"] == "중식1 정상 운영 특식"
    assert raw.slot_results["중식1"].outcome == ProcessingOutcome.SUCCESS


def test_blank_source_without_closure_is_ambiguous_empty(observation_output):
    scraper = DodamScraper(_Settings())

    with pytest.raises(MenuFetchException) as raised:
        scraper._parse_menu_from_html("   ", DATE)

    assert raised.value.raw_data is not None
    result = raised.value.raw_data.slot_results["__source__"]
    assert result.outcome == ProcessingOutcome.AMBIGUOUS_EMPTY
    assert result.reason_code == "SOURCE_EMPTY"


def test_missing_expected_general_table_structure_is_schema_changed(
    observation_output,
):
    scraper = HaksikScraper(_Settings())

    with pytest.raises(MenuFetchException) as raised:
        scraper._parse_menu_from_html(
            "<section><div class='renamed-menu'>김치찌개</div></section>", DATE
        )

    assert raised.value.raw_data is not None
    result = raised.value.raw_data.slot_results["__source__"]
    assert result.outcome == ProcessingOutcome.AMBIGUOUS_EMPTY
    assert result.reason_code == "SOURCE_SCHEMA_CHANGED"


def test_empty_general_menu_cell_is_source_empty(observation_output):
    scraper = FacultyScraper(_Settings())

    with pytest.raises(MenuFetchException) as raised:
        scraper._parse_menu_from_html(_general_html(menu="  "), DATE)

    assert raised.value.raw_data is not None
    result = raised.value.raw_data.slot_results["중식1"]
    assert result.outcome == ProcessingOutcome.AMBIGUOUS_EMPTY
    assert result.reason_code == "SOURCE_EMPTY"


def test_source_fingerprint_keeps_raw_text_only_in_menu_texts(observation_output):
    scraper = DodamScraper(_Settings())
    raw = scraper._parse_menu_from_html(
        _general_html(menu="&lt;html&gt;SECRET_TOKEN"), DATE
    )

    assert SENTINEL in raw.menu_texts["중식1"]
    result_json = json.dumps(raw.slot_results["중식1"].to_dict())
    event_json = observation_output.getvalue()
    expected_text = raw.menu_texts["중식1"]
    assert raw.slot_results["중식1"].source_sha256 == hashlib.sha256(
        expected_text.encode("utf-8")
    ).hexdigest()[:12]
    assert SENTINEL not in result_json
    assert SENTINEL not in event_json
    assert "SECRET_TOKEN" not in event_json


class _FailingResponse:
    status = 500

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        raise aiohttp.ClientResponseError(
            request_info=cast(aiohttp.RequestInfo, cast(object, None)),
            history=(),
            status=self.status,
            message=f"provider body {SENTINEL}",
        )


class _TimeoutRequest:
    async def __aenter__(self):
        raise asyncio.TimeoutError(SENTINEL)

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Session:
    def __init__(self, request):
        self.request = request

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, *args, **kwargs):
        return self.request


@pytest.mark.parametrize(
    ("fake_request", "error_type", "status"),
    [
        (_FailingResponse(), "ClientResponseError", 500),
        (_TimeoutRequest(), "TimeoutError", None),
    ],
)
async def test_general_http_failure_is_api_failure_without_provider_detail(
    monkeypatch, observation_output, fake_request, error_type, status
):
    monkeypatch.setattr(
        "functions.shared.repositories.scrapers.dodam_scraper.aiohttp.ClientSession",
        lambda: _Session(fake_request),
    )
    scraper = DodamScraper(_Settings())

    with pytest.raises(MenuFetchException) as raised:
        await scraper.scrape_menu(DATE)

    assert raised.value.outcome == ProcessingOutcome.API_FAILURE
    assert raised.value.__cause__ is None
    event = _events(observation_output)[-1]
    assert event["stage"] == "source_fetch"
    assert event["outcome"] == "API_FAILURE"
    assert event["error.type"] == error_type
    if status is None:
        assert "status" not in event
    else:
        assert event["status"] == status
    assert SENTINEL not in observation_output.getvalue()


async def test_dormitory_schema_wrapper_drops_raw_cause(
    monkeypatch, observation_output
):
    scraper = DormitoryScraper(_Settings())

    async def fetch_invalid_schema(date):
        return f"<section>{SENTINEL}</section>"

    monkeypatch.setattr(scraper, "_fetch_menu_html", fetch_invalid_schema)

    with pytest.raises(MenuFetchException) as raised:
        await scraper.scrape_menu(DATE)

    assert raised.value.reason_code == "SOURCE_SCHEMA_CHANGED"
    assert raised.value.__cause__ is None
    assert SENTINEL not in str(raised.value)
    assert SENTINEL not in observation_output.getvalue()


def _dormitory_html(headers, rows):
    header_html = "".join(f"<th>{value}</th>" for value in headers)
    row_html = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<table class="boxstyle02"><tr>{header_html}</tr>{row_html}</table>'


def test_dormitory_distinguishes_closed_empty_and_normal_slots(observation_output):
    scraper = DormitoryScraper(_Settings())
    html = _dormitory_html(
        ["날짜", "중식", "석식"],
        [
            ["07-13", "미운영", ""],
            ["07-14", "비빔밥\r\n된장국", "카레"],
            ["07-15", "정상 운영 특식", "카레"],
        ],
    )

    raw_menus = scraper._parse_html_to_raw_menu_data(html, 2026)

    closed_day, normal_day, operation_word_day = raw_menus
    assert closed_day.menu_texts == {}
    assert closed_day.slot_results["중식"].outcome == ProcessingOutcome.EXPECTED_EMPTY
    assert closed_day.slot_results["중식"].reason_code == "CLOSED_MARKER"
    assert closed_day.slot_results["석식"].outcome == ProcessingOutcome.AMBIGUOUS_EMPTY
    assert closed_day.slot_results["석식"].reason_code == "EMPTY_CELL"
    assert normal_day.menu_texts == {"중식": "비빔밥 된장국", "석식": "카레"}
    assert normal_day.slot_results["중식"].outcome == ProcessingOutcome.SUCCESS
    assert normal_day.slot_results["석식"].outcome == ProcessingOutcome.SUCCESS
    assert operation_word_day.menu_texts["중식"] == "정상 운영 특식"
    assert operation_word_day.slot_results["중식"].outcome == ProcessingOutcome.SUCCESS


def test_dormitory_missing_meal_column_is_recorded_per_day(observation_output):
    scraper = DormitoryScraper(_Settings())
    html = _dormitory_html(["날짜", "중식"], [["07-13", "비빔밥"]])

    raw = scraper._parse_html_to_raw_menu_data(html, 2026)[0]

    assert raw.menu_texts == {"중식": "비빔밥"}
    result = raw.slot_results["석식"]
    assert result.outcome == ProcessingOutcome.AMBIGUOUS_EMPTY
    assert result.reason_code == "MISSING_SLOT_COLUMN"


def test_dormitory_invalid_date_emits_fingerprint_without_raw_value(
    observation_output,
):
    scraper = DormitoryScraper(_Settings())
    invalid_date = f"bad-date-{SENTINEL}"
    invalid_date_html = "bad-date-&lt;html&gt;SECRET_TOKEN"
    html = _dormitory_html(
        ["날짜", "중식", "석식"], [[invalid_date_html, "비빔밥", "카레"]]
    )

    assert scraper._parse_html_to_raw_menu_data(html, 2026) == []
    event = _events(observation_output)[-1]
    assert event["event.name"] == "source_date_invalid"
    assert event["outcome"] == "AMBIGUOUS_EMPTY"
    assert event["reason_code"] == "INVALID_DATE"
    assert event["source_length"] == len(invalid_date.encode("utf-8"))
    assert len(event["source_sha256"]) == 12
    assert invalid_date not in observation_output.getvalue()
    assert SENTINEL not in observation_output.getvalue()
