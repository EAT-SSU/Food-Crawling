import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from functions import handler
from functions.clients import SpringExistenceError, SpringSlotReplaceError, SpringSlotReplaceResult
from functions.scraper import (
    AMBIGUOUS_EMPTY,
    EXPECTED_EMPTY,
    MealRecord,
    ScraperError,
    SourceParseError,
)


MONDAY = "20261102"
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=ZoneInfo("Asia/Seoul"))

HAKSIK_LUNCH = {"중식1": "제육볶음 쌀밥", "중식2": "돈까스 샐러드", "중식3": "비빔밥 된장국"}
DODAM_LUNCH = {"중식1": "닭갈비 쌀밥", "중식4": "샐러드볼 수프"}


def _records(restaurant, corners, date=MONDAY):
    return [MealRecord(date, restaurant, slot, text) for slot, text in corners.items()]


def _result(deleted=(), kept=()):
    return SpringSlotReplaceResult((), (), tuple(deleted), tuple(kept))


def _interpretation(api_key, restaurant, raw_text, source_english=()):
    names = raw_text.split()
    return {"menuNames": names, "mainMenus": [{"nameKo": names[0], "nameEn": "Main"}]}


class Harness:
    def __init__(self, records=(), existing=None, fetch_error=None, put=None, interpret=None):
        self.records = list(records)
        self.existing = existing or (lambda env, date, time: [])
        self.fetch_error = fetch_error
        self.fetch = AsyncMock(side_effect=self._fetch)
        self.get = AsyncMock(side_effect=self._get)
        self.put = put or AsyncMock(return_value=_result())
        self.interpret = interpret or AsyncMock(side_effect=_interpretation)
        self.slack = AsyncMock()

    async def _fetch(self, restaurant, date, *, requested_dates):
        if self.fetch_error is not None:
            raise self.fetch_error
        return [record for record in self.records if record.date in requested_dates]

    async def _get(self, *, base_url, environment, date, restaurant, time):
        value = self.existing(environment, date, time)
        if isinstance(value, Exception):
            raise value
        return value

    def run(self, **event):
        with (
            patch.object(handler, "_now_seoul", return_value=NOW),
            patch.object(handler, "fetch_meals", self.fetch),
            patch.object(handler, "spring_existing_meals", self.get),
            patch.object(handler, "replace_spring_slot", self.put),
            patch.object(handler, "interpret_menu", self.interpret),
            patch.object(handler, "send_slack_text", self.slack),
        ):
            response = handler.lambda_handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def puts(self, environment=None):
        return [
            call.kwargs
            for call in self.put.await_args_list
            if environment is None or call.kwargs["environment"] == environment
        ]

    def slack_texts(self):
        return [call.kwargs["text"] for call in self.slack.await_args_list]


def _schedule(restaurant, **extra):
    return {"restaurant": restaurant, "date": MONDAY, "environments": ["dev", "prod"], **extra}


def _existing_for(slot_meals):
    return lambda env, date, time: slot_meals.get(time, [])


@pytest.mark.parametrize(
    ("restaurant", "corners", "existing", "expected_interpreted"),
    [
        ("HAKSIK", HAKSIK_LUNCH, [], 3),
        ("HAKSIK", HAKSIK_LUNCH, [["제육볶음", "쌀밥"]], 2),
        ("HAKSIK", HAKSIK_LUNCH, [["제육볶음", "쌀밥"], ["돈까스", "샐러드"], ["비빔밥", "된장국"]], 0),
        ("DODAM", DODAM_LUNCH, [], 2),
        ("DODAM", DODAM_LUNCH, [["닭갈비", "쌀밥"]], 1),
        ("DODAM", DODAM_LUNCH, [["닭갈비", "쌀밥"], ["샐러드볼", "수프"]], 0),
    ],
    ids=["haksik-all-new", "haksik-some", "haksik-all-existing", "dodam-all-new", "dodam-some", "dodam-all-existing"],
)
def test_fill_multi_corner_lunch_is_checked_per_corner(restaurant, corners, existing, expected_interpreted):
    harness = Harness(_records(restaurant, corners), existing=_existing_for({"LUNCH": existing}))

    status, body = harness.run(**_schedule(restaurant, final=True))

    assert status == 200
    assert harness.interpret.await_count == expected_interpreted
    if expected_interpreted == 0:
        harness.put.assert_not_awaited()
        harness.slack.assert_not_awaited()
        assert body["missing"] == []
        return
    for environment in ("dev", "prod"):
        (put,) = harness.puts(environment)
        assert put["time"] == "LUNCH"
        assert [item["menuNames"] for item in put["items"]] == [text.split() for text in corners.values()]
        reused = [item for item in put["items"] if item["mainMenus"] is None]
        assert len(reused) == len(existing)
    assert body["missing"] == []
    assert len(harness.slack_texts()) == 1
    assert all(f"• {slot}:" in harness.slack_texts()[0] for slot in corners)


def test_force_reinterprets_every_corner_once_and_puts_both_environments():
    existing = [text.split() for text in HAKSIK_LUNCH.values()]
    harness = Harness(_records("HAKSIK", HAKSIK_LUNCH), existing=_existing_for({"LUNCH": existing}))

    harness.run(**_schedule("HAKSIK", mode="force"))

    assert harness.interpret.await_count == 3
    assert len(harness.puts("dev")) == len(harness.puts("prod")) == 1
    assert all(item["mainMenus"] for item in harness.puts("prod")[0]["items"])
    harness.slack.assert_not_awaited()


def test_slot_mapping_comes_from_config_haksik_dinner_is_morning():
    harness = Harness(_records("HAKSIK", {"석식1": "김밥 라면"}))

    harness.run(**_schedule("HAKSIK"))

    assert {put["time"] for put in harness.puts()} == {"MORNING"}
    assert harness.puts()[0]["items"][0]["price"] == 1000


def test_get_failure_skips_put_for_that_environment_only():
    def existing(env, date, time):
        return SpringExistenceError("down") if env == "prod" else []

    harness = Harness(_records("DODAM", DODAM_LUNCH), existing=existing)

    _, body = harness.run(**_schedule("DODAM", final=True))

    assert harness.puts("prod") == []
    assert len(harness.puts("dev")) == 1
    assert {(item["corner"], item["environment"]) for item in body["missing"]} == {
        ("중식1", "prod"),
        ("중식4", "prod"),
    }


def test_readable_slot_with_one_existing_meal_still_reports_missing_corners_on_final():
    harness = Harness(
        _records("HAKSIK", HAKSIK_LUNCH),
        existing=_existing_for({"LUNCH": [["제육볶음", "쌀밥"]]}),
        put=AsyncMock(side_effect=SpringSlotReplaceError("failed")),
    )

    _, body = harness.run(**_schedule("HAKSIK", final=True))

    assert [item["corner"] for item in body["missing"]] == ["중식1", "중식2", "중식3"]
    assert any("마감 시점까지" in text for text in harness.slack_texts())


@pytest.mark.parametrize(
    "event",
    [
        {"restaurant": "HAKSIK", "date": "20261030", "environments": ["dev", "prod"], "mode": "force"},
        {"restaurant": "HAKSIK", "date": "20261030", "environments": ["dev", "prod"]},
    ],
)
def test_past_dates_are_never_fetched_or_put(event):
    harness = Harness(_records("HAKSIK", HAKSIK_LUNCH, date="20261030"))

    _, body = harness.run(**event, final=True)

    assert body["dates"] == []
    harness.fetch.assert_not_awaited()
    harness.put.assert_not_awaited()
    harness.slack.assert_not_awaited()


def test_dormitory_current_week_fetches_once_from_today_with_week_dates():
    harness = Harness([])

    harness.run(restaurant="DORMITORY", dates="current_week")

    (call,) = harness.fetch.await_args_list
    assert call.args == ("DORMITORY", MONDAY)
    assert call.kwargs["requested_dates"] == [f"202611{day:02d}" for day in range(2, 9)]


def test_duplicate_corners_are_deduped_and_empty_interpretations_never_put():
    harness = Harness(_records("HAKSIK", {"중식1": "제육볶음 쌀밥", "중식2": "제육볶음 쌀밥"}))
    harness.run(**_schedule("HAKSIK"))
    assert [len(put["items"]) for put in harness.puts()] == [1, 1]

    empty = Harness(
        _records("HAKSIK", {"중식1": "제육볶음"}),
        interpret=AsyncMock(return_value={"menuNames": [], "mainMenus": []}),
    )
    empty.run(**_schedule("HAKSIK"))
    empty.put.assert_not_awaited()


def test_interpretation_failure_skips_the_whole_slot():
    interpret = AsyncMock(side_effect=[{"menuNames": ["제육볶음"], "mainMenus": []}, ValueError("bad")])
    harness = Harness(_records("DODAM", DODAM_LUNCH), interpret=interpret)

    harness.run(**_schedule("DODAM"))

    harness.put.assert_not_awaited()


@pytest.mark.parametrize("final", [False, True])
def test_blocked_source_with_existing_prod_meals_is_silent(final):
    harness = Harness(
        fetch_error=SourceParseError(MONDAY, "DORMITORY", "SOURCE_BLOCKED"),
        existing=lambda env, date, time: [["기존메뉴"]] if env == "prod" else [],
    )

    _, body = harness.run(restaurant="DORMITORY", date=MONDAY, environments=["dev", "prod"], final=final)

    harness.put.assert_not_awaited()
    harness.slack.assert_not_awaited()
    assert body["missing"] == []
    assert body["unreadable"] == [{"date": MONDAY, "time": "DINNER"}, {"date": MONDAY, "time": "LUNCH"}]


@pytest.mark.parametrize("final", [False, True])
def test_blocked_source_with_empty_spring_alerts_only_on_final(final):
    harness = Harness(fetch_error=ScraperError(MONDAY, "DORMITORY", "SOURCE_HTTP_ERROR", "API_FAILURE"))

    _, body = harness.run(restaurant="DORMITORY", date=MONDAY, environments=["dev", "prod"], final=final)

    harness.put.assert_not_awaited()
    if final:
        assert [(item["time"], item["corner"]) for item in body["missing"]] == [
            ("DINNER", "전체"),
            ("LUNCH", "전체"),
        ]
        (text,) = harness.slack_texts()
        assert "20261102 LUNCH 전체 (prod)" in text
    else:
        harness.get.assert_not_awaited()
        harness.slack.assert_not_awaited()


def test_dormitory_unposted_slot_is_not_put_while_other_slot_is():
    records = [
        MealRecord(MONDAY, "DORMITORY", "중식", "", outcome=AMBIGUOUS_EMPTY, reason_code="EMPTY_CELL"),
        MealRecord(MONDAY, "DORMITORY", "석식", "카레 쌀밥"),
    ]
    harness = Harness(records)

    _, body = harness.run(restaurant="DORMITORY", date=MONDAY, environments=["dev", "prod"], final=True)

    assert {put["time"] for put in harness.puts()} == {"DINNER"}
    assert [(item["time"], item["corner"]) for item in body["missing"]] == [("LUNCH", "중식")]


def test_closure_notices_are_not_published_or_alerted():
    records = [MealRecord(MONDAY, "DODAM", "중식1", "한글날 로 휴무 입니다.", outcome=EXPECTED_EMPTY)]
    harness = Harness(records)

    _, body = harness.run(**_schedule("DODAM", final=True))

    harness.put.assert_not_awaited()
    harness.slack.assert_not_awaited()
    assert body["missing"] == []


def test_whole_day_holiday_is_not_alerted():
    harness = Harness(fetch_error=ScraperError(MONDAY, "HAKSIK", "HOLIDAY", EXPECTED_EMPTY))

    _, body = harness.run(**_schedule("HAKSIK", final=True))

    assert body["unreadable"] == [] and body["missing"] == []
    harness.slack.assert_not_awaited()


def test_summary_only_when_put_changes_meals():
    existing = [["제육볶음", "쌀밥"], ["낡은메뉴"]]
    unchanged = Harness(
        _records("FACULTY", {"중식1": "제육볶음 쌀밥"}),
        existing=_existing_for({"LUNCH": [["제육볶음", "쌀밥"]]}),
    )
    unchanged.run(**_schedule("FACULTY", mode="force"))
    unchanged.put.assert_awaited()
    unchanged.slack.assert_not_awaited()

    deleted = Harness(
        _records("FACULTY", {"중식1": "제육볶음 쌀밥"}),
        existing=_existing_for({"LUNCH": existing}),
        put=AsyncMock(return_value=_result(deleted=[7])),
    )
    deleted.run(**_schedule("FACULTY"))
    assert len(deleted.slack_texts()) == 1
    assert "• 중식1: 제육볶음, 쌀밥" in deleted.slack_texts()[0]


def test_kept_with_reviews_sends_separate_warning():
    harness = Harness(
        _records("FACULTY", {"중식1": "제육볶음 쌀밥"}),
        existing=_existing_for({"LUNCH": [["리뷰메뉴"]]}),
        put=AsyncMock(return_value=_result(kept=[42])),
    )

    harness.run(**_schedule("FACULTY", environments=["prod"]))

    texts = harness.slack_texts()
    assert any("리뷰가 있어 유지된 식단 42" in text for text in texts)
    assert any("• 중식1" in text for text in texts)


def test_manual_invocation_defaults_to_dev_only():
    harness = Harness(_records("FACULTY", {"중식1": "제육볶음 쌀밥"}))

    _, body = harness.run(restaurant="FACULTY", date=MONDAY)

    assert body["environments"] == ["dev"]
    assert {call.kwargs["environment"] for call in harness.get.await_args_list} == {"dev"}
    assert [put["environment"] for put in harness.puts()] == ["dev"]


def test_dry_run_makes_no_put_and_no_slack():
    harness = Harness(_records("HAKSIK", HAKSIK_LUNCH))

    status, body = harness.run(**_schedule("HAKSIK", dry_run=True, final=True))

    assert status == 200
    harness.put.assert_not_awaited()
    harness.slack.assert_not_awaited()
    assert [(item["date"], item["time"], item["environment"]) for item in body["planned"]] == [
        (MONDAY, "LUNCH", "dev"),
        (MONDAY, "LUNCH", "prod"),
    ]
    assert [item["menuNames"] for item in body["planned"][0]["items"]] == [
        text.split() for text in HAKSIK_LUNCH.values()
    ]


def test_next_week_dates_from_sunday_schedule():
    request = handler.parse_event({"restaurant": "dodam", "dates": "next_week"})
    assert isinstance(request, dict)
    sunday = datetime(2026, 11, 1, 16, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    assert handler.target_dates(request, 6, sunday) == [f"202611{day:02d}" for day in range(2, 8)]
    remaining = {**request, "dates": "remaining_week"}
    thursday = datetime(2026, 11, 5, 16, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    assert handler.target_dates(remaining, 5, thursday) == ["20261105", "20261106"]


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"restaurant": "HAKSIK"},
        {"restaurant": "HAKSIK", "dates": "someday"},
        {"restaurant": "HAKSIK", "date": "20261340"},
        {"restaurant": "HAKSIK", "date": MONDAY, "mode": "append"},
        {"restaurant": "HAKSIK", "date": MONDAY, "environments": ["staging"]},
        {"restaurant": "HAKSIK", "date": MONDAY, "final": "true"},
        {"restaurant": "CAFE", "date": MONDAY},
    ],
)
def test_invalid_events_return_400_without_side_effects(event):
    harness = Harness()

    status, body = harness.run(**event)

    assert status == 400 and body["success"] is False
    harness.fetch.assert_not_awaited()
