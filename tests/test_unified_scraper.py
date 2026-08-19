import json
from pathlib import Path

import pytest

from functions.scraper import (
    AMBIGUOUS_EMPTY,
    API_FAILURE,
    EXPECTED_EMPTY,
    SUCCESS,
    HolidayError,
    ScraperError,
    SourceParseError,
    fetch_meals,
    parse_dormitory_html,
    parse_menu_html,
    parse_soongguri_html,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/characterization"
SOURCE = json.loads((FIXTURES / "source_contracts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("restaurant", ["DODAM", "HAKSIK", "FACULTY"])
def test_soongguri_characterization_fixtures_use_one_parser(restaurant):
    expected = SOURCE[restaurant]
    html = (FIXTURES / f"{restaurant.lower()}.html").read_text(encoding="utf-8")

    records = parse_menu_html(html, restaurant, [expected["date"]])

    assert {record.source_slot: record.raw_text for record in records} == expected["menu_texts"]
    assert {record.source_slot: record.outcome for record in records} == expected["slot_outcomes"]
    assert all(record.date == expected["date"] for record in records)
    assert all(record.restaurant == restaurant for record in records)


@pytest.mark.parametrize(
    ("restaurant", "expected_evidence"),
    [
        ("DODAM", {"중식1": ("Spicy Pork",), "석식1": ("Pork Cutlet",)}),
        ("HAKSIK", {"중식1": ("Bibimbap",), "석식1": ("One Dollar Breakfast",)}),
        ("FACULTY", {"중식1": ("Beef Bulgogi",)}),
    ],
)
def test_soongguri_source_english_is_extracted_verbatim(restaurant, expected_evidence):
    html = (FIXTURES / f"{restaurant.lower()}.html").read_text(encoding="utf-8")

    records = parse_soongguri_html(html, SOURCE[restaurant]["date"], restaurant)

    assert {record.source_slot: record.source_english for record in records} == expected_evidence
    for record in records:
        assert record.source_english_evidence == record.source_english
        assert all(evidence in record.raw_text for evidence in record.source_english)


def test_dormitory_characterization_fixture_selects_requested_dates():
    expected = SOURCE["DORMITORY"]
    html = (FIXTURES / "dormitory.html").read_text(encoding="utf-8")

    records = parse_dormitory_html(html, expected["dates"])

    by_date = {
        date: [record for record in records if record.date == date]
        for date in expected["dates"]
    }
    assert [
        {
            record.source_slot: record.raw_text
            for record in by_date[date]
            if record.outcome == SUCCESS
        }
        for date in expected["dates"]
    ] == expected["menu_texts"]
    assert [
        {record.source_slot: record.outcome for record in by_date[date]}
        for date in expected["dates"]
    ] == expected["slot_outcomes"]
    assert all(record.restaurant == "DORMITORY" for record in records)
    assert all(record.source_english == () for record in records)


def _dormitory_html(headers, rows):
    header = "".join(f"<th>{value}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<table class="boxstyle02"><tr>{header}</tr>{body}</table>'


def test_dormitory_selects_requested_rows_after_the_seventh_row():
    rows = [
        [f"07-{day:02d}", f"중식-{day}", f"석식-{day}"]
        for day in range(24, 32)
    ] + [["08-01", "중식-1", "석식-1"], ["08-02", "중식-2", "석식-2"]]
    html = _dormitory_html(["날짜", "중식", "석식"], rows)

    records = parse_dormitory_html(html, ["20260801", "20260802"])

    assert [(record.date, record.source_slot, record.raw_text) for record in records] == [
        ("20260801", "중식", "중식-1"),
        ("20260801", "석식", "석식-1"),
        ("20260802", "중식", "중식-2"),
        ("20260802", "석식", "석식-2"),
    ]


def test_soongguri_holiday_and_slot_empty_outcomes_are_explicit():
    with pytest.raises(HolidayError) as raised:
        parse_soongguri_html("<main>오늘은 쉽니다.</main>", "20260713", "DODAM")
    assert raised.value.outcome == EXPECTED_EMPTY
    assert raised.value.reason_code == "HOLIDAY"

    records = parse_soongguri_html(
        "<table>"
        '<tr><td class="menu_nm">중식1</td><td>미운영</td></tr>'
        '<tr><td class="menu_nm">석식1</td><td>비빔밥</td></tr>'
        "</table>",
        "20260713",
        "DODAM",
    )
    assert records[0].outcome == EXPECTED_EMPTY
    assert records[0].reason_code == "CLOSED_MARKER"
    assert records[1].outcome == SUCCESS


def test_soongguri_empty_and_malformed_sources_fail_deterministically():
    with pytest.raises(SourceParseError) as empty:
        parse_soongguri_html("", "20260713", "HAKSIK")
    assert empty.value.reason_code == "SOURCE_EMPTY"
    assert empty.value.outcome == AMBIGUOUS_EMPTY

    with pytest.raises(SourceParseError) as malformed:
        parse_soongguri_html("<section>renamed menu</section>", "20260713", "HAKSIK")
    assert malformed.value.reason_code == "SOURCE_SCHEMA_CHANGED"

    with pytest.raises(SourceParseError) as missing_cell:
        parse_soongguri_html(
            '<table><tr><td class="menu_nm">중식1</td></tr></table>',
            "20260713",
            "HAKSIK",
        )
    assert missing_cell.value.reason_code == "SOURCE_EMPTY"


def test_dormitory_missing_header_cell_and_malformed_rowspan_are_explicit():
    with pytest.raises(SourceParseError) as missing_header:
        parse_dormitory_html(
            _dormitory_html(["요일", "중식", "석식"], [["월", "밥", "국"]]),
            ["20260713"],
        )
    assert missing_header.value.reason_code == "MISSING_DATE_HEADER"

    records = parse_dormitory_html(
        _dormitory_html(["날짜", "중식", "석식"], [["07-13", "비빔밥"]]),
        ["20260713"],
    )
    assert records[1].source_slot == "석식"
    assert records[1].outcome == AMBIGUOUS_EMPTY
    assert records[1].reason_code == "MISSING_SLOT_COLUMN"

    malformed_span = (
        '<table class="boxstyle02">'
        "<tr><th>날짜</th><th>중식</th><th>석식</th></tr>"
        '<tr><td rowspan="3">07-13</td><td>비빔밥</td><td>카레</td></tr>'
        "</table>"
    )
    with pytest.raises(SourceParseError) as malformed:
        parse_dormitory_html(malformed_span, ["20260713"])
    assert malformed.value.reason_code == "SOURCE_SCHEMA_CHANGED"


class _Response:
    def __init__(self, html="", error=None):
        self.html = html
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    async def text(self):
        return self.html


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_fetch_meals_preserves_source_url_and_date_formats():
    dodam_html = (FIXTURES / "dodam.html").read_text(encoding="utf-8")
    soongguri_session = _Session(_Response(dodam_html))

    records = await fetch_meals(
        "DODAM",
        "20260713",
        session_factory=lambda: soongguri_session,
        soongguri_base_url="https://source.example/menu",
    )

    assert records[0].restaurant == "DODAM"
    assert soongguri_session.calls == [
        (("https://source.example/menu?rcd=2&sdt=20260713",), {})
    ]

    dorm_html = (FIXTURES / "dormitory.html").read_text(encoding="utf-8")
    dormitory_session = _Session(_Response(dorm_html))
    await fetch_meals(
        "DORMITORY",
        "20260713",
        requested_dates=["20260713", "20260714"],
        session_factory=lambda: dormitory_session,
        dormitory_base_url="https://source.example/dormitory",
    )
    assert dormitory_session.calls == [
        (
            ("https://source.example/dormitory",),
            {
                "params": {
                    "viewform": "B0001_foodboard_list",
                    "gyear": 2026,
                    "gmonth": 7,
                    "gday": 13,
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_fetch_failure_uses_one_attempt_and_preserves_error_classification():
    failure = TimeoutError("provider detail")
    session = _Session(_Response(error=failure))

    with pytest.raises(ScraperError) as raised:
        await fetch_meals(
            "FACULTY",
            "20260713",
            session_factory=lambda: session,
            soongguri_base_url="https://source.example/menu",
        )

    assert len(session.calls) == 1
    assert raised.value.reason_code == "SOURCE_HTTP_ERROR"
    assert raised.value.outcome == API_FAILURE
    assert raised.value.error_type == "TimeoutError"
    assert raised.value.__cause__ is None
    assert "provider detail" not in str(raised.value)
