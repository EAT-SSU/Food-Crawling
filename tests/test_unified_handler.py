import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from functions import handler, menu_ai  # pyright: ignore[reportAttributeAccessIssue]


ROOT = Path(__file__).resolve().parents[1]
INVOCATIONS = json.loads(
    (ROOT / "tests/fixtures/characterization/invocations.json").read_text(
        encoding="utf-8"
    )
)


class _Context:
    aws_request_id = "unified-handler-request"


@pytest.fixture(autouse=True)
def _mock_spring_existence():
    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(
            handler,
            "_now_seoul",
            return_value=datetime(2026, 7, 13, 8, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        ),
    ):
        yield


def _raw(date: str, restaurant: str) -> dict[str, str]:
    slot = "석식1" if restaurant == "HAKSIK" else "중식1"
    return {
        "date": date,
        "restaurant": restaurant,
        "source_slot": slot,
        "raw_text": "제육볶음 Pork",
    }


def _raw_slot(date: str, restaurant: str, slot: str) -> dict[str, str]:
    return {**_raw(date, restaurant), "source_slot": slot}


def _complete_raw(date: str, restaurant: str) -> list[dict[str, str]]:
    slots = ("중식1",) if restaurant == "FACULTY" else ("중식1", "석식1")
    return [_raw_slot(date, restaurant, slot) for slot in slots]


def _haksik_lunch_corners(date: str) -> list[dict[str, str]]:
    return [
        {**_raw_slot(date, "HAKSIK", "중식1"), "raw_text": "제육볶음 쌀밥"},
        {**_raw_slot(date, "HAKSIK", "중식2"), "raw_text": "돈까스 샐러드"},
        {**_raw_slot(date, "HAKSIK", "중식3"), "raw_text": "비빔밥 국"},
    ]


def _accepted(unmatched=None, warnings=None):
    return SimpleNamespace(
        meal_ids=(),
        unmatched_main_menus=(tuple(unmatched),) if unmatched else (),
        deleted_meal_ids=(),
        kept_with_reviews=(),
        warnings=warnings or [],
    )


def _dependencies(entry):
    restaurant = entry["restaurant"]
    dates = entry.get("result_dates", entry.get("current_dates", [entry.get("expected_date", "20260713")]))
    if restaurant == "DORMITORY" and entry["kind"] == "scrape":
        scrape = AsyncMock(
            return_value=[record for date in dates for record in _complete_raw(date, restaurant)]
        )
    elif restaurant == "DORMITORY":
        scrape = AsyncMock(
            side_effect=lambda _config, target_date, **_kwargs: _complete_raw(
                target_date, restaurant
            )
        )
    else:
        scrape = AsyncMock(
            side_effect=lambda _config, target_date: _complete_raw(target_date, restaurant)
        )
    interpret = AsyncMock(
        return_value={
            "menuNames": ["제육볶음", "쌀밥"],
            "mainMenus": [{"nameKo": "제육볶음", "nameEn": "Pork"}],
        }
    )
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock(return_value=True)
    return scrape, interpret, publish, slack


def _date_summary_dates(slack: AsyncMock) -> list[str]:
    return [
        call.args[1]["date"]
        for call in slack.await_args_list
        if call.args[1]["type"] == "date_summary"
    ]


@pytest.mark.parametrize(
    "entry", INVOCATIONS["operations"], ids=lambda item: item["operation"]
)
def test_all_scrape_and_schedule_operations_share_one_dispatch_boundary(entry):
    scrape, interpret, publish, slack = _dependencies(entry)
    event = {**entry["event"], "operation": entry["operation"]}

    def fixed_week_dates(day_count, *, next_week):
        key = "next_dates" if next_week and "next_dates" in entry else "current_dates"
        return entry.get(key, [entry.get("expected_date", "20260713")])[:day_count]

    original_run = asyncio.run
    run_count = 0

    def counting_run(coroutine):
        nonlocal run_count
        run_count += 1
        return original_run(coroutine)

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
        patch.object(handler, "_week_dates", side_effect=fixed_week_dates),
        patch.object(handler.asyncio, "run", side_effect=counting_run),
    ):
        response = handler.lambda_handler(event, _Context())

    assert response["statusCode"] == entry["expected_status"]
    assert response["headers"] == {"Content-Type": "application/json; charset=utf-8"}
    assert run_count == 1
    assert slack.await_count == entry["expected_slack_count"]
    expected_environments = entry["destination_environments"]
    actual_environments = [call.args[4] for call in publish.await_args_list]
    assert set(actual_environments) == set(expected_environments)
    assert len(actual_environments) == interpret.await_count * len(expected_environments)


def test_manual_delayed_schedule_uses_current_week_and_target_date_wins():
    entry = next(
        item for item in INVOCATIONS["operations"] if item["operation"] == "schedule_dodam"
    )
    scrape, interpret, publish, slack = _dependencies(entry)
    current = entry["current_dates"]
    event = {**entry["manual_event"], "operation": entry["operation"]}

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
        patch.object(handler, "_week_dates", return_value=current),
    ):
        handler.lambda_handler(event, _Context())

    assert [call.args[1] for call in scrape.await_args_list] == current

    scrape.reset_mock()
    targeted = {**event, "target_date": "20260715"}
    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        handler.lambda_handler(targeted, _Context())

    scrape.assert_awaited_once()
    assert scrape.await_args is not None
    assert scrape.await_args.args[1] == "20260715"


@pytest.mark.parametrize(
    "retry_type", [handler.RetryableEmptyMenuError, handler.RetryableApiSendError]
)
def test_dormitory_retry_exceptions_escape_by_identity_without_slack(retry_type):
    retry_error = retry_type("20260713")
    scrape = AsyncMock(side_effect=retry_error)
    slack = AsyncMock()

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", AsyncMock()),
        patch.object(handler, "replace_slot", AsyncMock()),
        patch.object(handler, "notify_slack", slack),
    ):
        with pytest.raises(retry_type) as raised:
            handler.lambda_handler(
                {
                    "operation": "schedule_dormitory",
                    "trigger": "step_functions",
                    "target_date": "20260713",
                },
                _Context(),
            )

    assert raised.value is retry_error
    slack.assert_not_awaited()


def test_dormitory_critical_publication_failure_becomes_retry_without_slack():
    scrape = AsyncMock(return_value=_complete_raw("20260713", "DORMITORY"))
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(
        side_effect=[
            _accepted(),
            RuntimeError("prod unavailable"),
            _accepted(),
            _accepted(),
        ]
    )
    slack = AsyncMock()

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {
                "operation": "schedule_dormitory",
                "target_date": "20260713",
                "notify_summary": False,
            },
            _Context(),
        )

    assert json.loads(response["body"])["remaining_missing"] == [
        {
            "date": "20260713",
            "slot": "중식1",
            "time": "LUNCH",
            "environments": ["prod"],
        }
    ]
    slack.assert_not_awaited()


def test_final_failure_loads_one_operation_and_calls_only_slack(monkeypatch):
    monkeypatch.delenv("GPT_API_KEY", raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("DEV_API_BASE_URL", raising=False)
    entry = INVOCATIONS["final_failure"]
    event = {**entry["event"], "operation": entry["operation"]}
    slack = AsyncMock(return_value=True)
    config_loader = patch.object(
        handler,
        "load_operation_config",
        wraps=handler.load_operation_config,
    )

    with (
        config_loader as loader,
        patch.object(handler, "scrape", AsyncMock()) as scrape,
        patch.object(handler, "interpret_menu", AsyncMock()) as interpret,
        patch.object(handler, "replace_slot", AsyncMock()) as publish,
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(event, _Context())

    assert json.loads(response["body"]) == {
        "message": "final failure notified",
        "error_type": "RetryableEmptyMenuError",
    }
    loader.assert_called_once_with("notify_final_failure")
    scrape.assert_not_awaited()
    interpret.assert_not_awaited()
    publish.assert_not_awaited()
    slack.assert_awaited_once()
    assert slack.await_args is not None
    assert slack.await_args.args[1]["restaurant"] == "기숙사식당"


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        ({"target_date": "20260713"}, "missing operation"),
        ({"operation": "unknown_operation", "target_date": "20260713"}, "unknown operation"),
    ],
)
def test_missing_and_unknown_operations_are_deterministic_and_side_effect_free(event, reason):
    boundaries = [AsyncMock() for _ in range(4)]
    with (
        patch.object(handler, "scrape", boundaries[0]),
        patch.object(handler, "interpret_menu", boundaries[1]),
        patch.object(handler, "replace_slot", boundaries[2]),
        patch.object(handler, "notify_slack", boundaries[3]),
    ):
        response = handler.lambda_handler(event, _Context())

    assert response["statusCode"] == 400
    assert json.loads(response["body"]) == {"success": False, "error": reason}
    assert all(boundary.await_count == 0 for boundary in boundaries)


def test_strict_ai_failure_skips_spring_and_notifies_once():
    scrape = AsyncMock(return_value=[_raw("20260713", "DODAM")])
    interpret = AsyncMock(side_effect=ValueError("invalid tool output"))
    publish = AsyncMock()
    slack = AsyncMock(return_value=True)

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_dodam", "target_date": "20260713"},
            _Context(),
        )

    assert response["statusCode"] == 400
    publish.assert_not_awaited()
    slack.assert_awaited_once()


def test_unmatched_main_menus_are_warned_once_without_reposting():
    scrape = AsyncMock(return_value=[_raw("20260713", "DODAM")])
    interpret = AsyncMock(
        return_value={
            "menuNames": ["제육볶음"],
            "mainMenus": [{"nameKo": "제육볶음", "nameEn": "Pork"}],
        }
    )
    unmatched = [{"nameKo": "제육볶음", "nameEn": "Pork"}]
    publish = AsyncMock(return_value=_accepted(unmatched=unmatched))
    slack = AsyncMock(return_value=True)

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_dodam", "target_date": "20260713"},
            _Context(),
        )

    assert response["statusCode"] == 200
    publish.assert_awaited_once()
    slack.assert_awaited_once()
    assert slack.await_args is not None
    notification = slack.await_args.args[1]
    assert notification["warnings"] == [
        {
            "slot": "중식1",
            "stage": "unmatched",
            "reason": "unmatched main menus",
            "items": unmatched,
        }
    ]


def test_date_summary_maps_only_interpreted_main_menus_by_source_slot():
    scrape = AsyncMock(
        return_value=[
            {
                **_raw("20260713", "DODAM"),
                "source_slot": "중식1",
                "raw_text": "제육볶음 Spicy Pork 쌀밥",
            },
            {
                **_raw("20260713", "DODAM"),
                "source_slot": "석식1",
                "raw_text": "된장찌개 Soybean Paste Stew",
            },
        ]
    )
    interpret = AsyncMock(
        side_effect=[
            {
                "menuNames": ["제육볶음", "쌀밥"],
                "mainMenus": [{"nameKo": "제육볶음", "nameEn": "Spicy Pork"}],
            },
            {"menuNames": ["된장찌개"], "mainMenus": []},
        ]
    )
    publish = AsyncMock(
        side_effect=[
            _accepted(
                unmatched=[
                    {"nameKo": "공급자메뉴", "nameEn": "Provider Secret"}
                ]
            ),
            _accepted(),
        ]
    )
    slack = AsyncMock(return_value=True)

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_dodam", "target_date": "20260713"},
            _Context(),
        )

    assert response["statusCode"] == 200
    slack.assert_awaited_once()
    assert slack.await_args is not None
    notification = slack.await_args.args[1]
    assert notification["menus"] == {
        "중식1": ["제육볶음", "쌀밥"],
        "석식1": ["된장찌개"],
    }
    assert notification["main_menus"] == {
        "중식1": [{"nameKo": "제육볶음", "nameEn": "Spicy Pork"}]
    }
    assert "공급자메뉴" not in str(notification["main_menus"])


def test_operation_loader_uses_flat_config_module_and_operation_policy():
    config = handler.load_operation_config("scrape_haksik")
    assert config is not None
    assert config["restaurant"] == "HAKSIK"
    assert config["gpt_api_key"] == "test-gpt-key"


def test_handler_has_no_dormant_duplicate_operation_or_restaurant_policy():
    assert not hasattr(handler, "_RESTAURANTS")
    assert not hasattr(handler, "_OPERATION_SPECS")


def test_final_failure_configuration_requires_only_slack(monkeypatch):
    monkeypatch.delenv("GPT_API_KEY")
    monkeypatch.delenv("API_BASE_URL")
    monkeypatch.delenv("DEV_API_BASE_URL")

    config = handler.load_operation_config("notify_final_failure")

    assert config is not None
    assert set(config) == {
        "operation",
        "kind",
        "restaurant",
        "name_ko",
        "week_days",
        "slots",
        "special_note",
        "slack_webhook_url",
    }


def test_final_failure_slack_error_remains_explicit():
    slack_error = RuntimeError("Slack unavailable")
    with patch.object(handler, "notify_slack", AsyncMock(side_effect=slack_error)):
        with pytest.raises(RuntimeError) as raised:
            handler.lambda_handler(
                {
                    "operation": "notify_final_failure",
                    "error_type": "RetryableEmptyMenuError",
                    "target_date": "20260713",
                },
                _Context(),
            )

    assert raised.value is slack_error


def test_empty_source_records_bypass_gpt_and_use_safe_summary():
    scrape = AsyncMock(
        return_value=[
            {
                "date": "20260713",
                "restaurant": "DODAM",
                "source_slot": "중식1",
                "raw_text": "미운영",
                "source_english": (),
                "outcome": "EXPECTED_EMPTY",
                "reason_code": "CLOSED_MARKER",
            }
        ]
    )
    interpret = AsyncMock()
    publish = AsyncMock()
    slack = AsyncMock()
    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_dodam", "target_date": "20260713"}, _Context()
        )

    assert response["statusCode"] == 200
    interpret.assert_not_awaited()
    publish.assert_not_awaited()
    assert slack.await_args is not None
    assert slack.await_args.args[1]["empty_reasons"] == {"중식1": "CLOSED_MARKER"}


def test_partial_dormitory_week_isolates_missing_date_and_processes_others():
    dates = [f"202607{day:02d}" for day in range(13, 20)]
    scrape = AsyncMock(
        side_effect=lambda _config, target_date, **_kwargs: (
            []
            if target_date == dates[2]
            else _complete_raw(target_date, "DORMITORY")
        )
    )
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    body = json.loads(response["body"])
    results = body["results"]
    missing = next(result for result in results if result["date"] == dates[2])
    assert response["statusCode"] == 200
    assert missing["success"] is False
    assert missing["error_slots"] == {"전체": "MISSING_DATE"}
    assert interpret.await_count == 12
    assert publish.await_count == 24
    assert _date_summary_dates(slack) == [
        date for date in dates if date != dates[2]
    ]
    assert {item["date"] for item in body["remaining_missing"]} == {dates[2]}


def test_weekly_dormitory_failure_is_isolated_to_its_date():
    dates = ["20260921", "20260922"]
    failed_record = {
        "date": dates[1],
        "restaurant": "DORMITORY",
        "source_slot": "중식",
        "raw_text": "",
        "source_english": (),
        "outcome": "AMBIGUOUS_EMPTY",
        "reason_code": "EMPTY_CELL",
    }
    scrape = AsyncMock(
        side_effect=lambda _config, target_date, **_kwargs: (
            _complete_raw(target_date, "DORMITORY")
            if target_date == dates[0]
            else [failed_record]
        )
    )
    slack = AsyncMock()

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", AsyncMock(return_value=_accepted())),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "schedule_dormitory", "schedule_mode": "current_week"},
            _Context(),
        )

    results = json.loads(response["body"])["results"]
    assert response["statusCode"] == 200
    assert [result["success"] for result in results] == [True, False]
    assert results[1]["error_slots"] == {"중식": "EMPTY_CELL"}
    assert _date_summary_dates(slack) == [dates[0]]


def test_complete_dormitory_week_including_closed_date_keeps_current_behavior():
    dates = [f"202607{day:02d}" for day in range(13, 20)]
    closed_record = {
        "date": dates[-1],
        "restaurant": "DORMITORY",
        "source_slot": "전체",
        "raw_text": "미운영",
        "source_english": (),
        "outcome": "EXPECTED_EMPTY",
        "reason_code": "CLOSED_MARKER",
    }
    scrape = AsyncMock(
        side_effect=lambda _config, target_date, **_kwargs: (
            [closed_record]
            if target_date == dates[-1]
            else _complete_raw(target_date, "DORMITORY")
        )
    )
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()
    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    assert scrape.await_count == 7
    assert all(call.kwargs["requested_dates"] == [call.args[1]] for call in scrape.await_args_list)
    assert response["statusCode"] == 200
    assert interpret.await_count == 12
    assert publish.await_count == 24
    assert _date_summary_dates(slack) == dates[:-1]


def test_dormitory_closed_weekend_is_complete_without_ai_or_spring_calls():
    dates = [f"202608{day:02d}" for day in range(24, 31)]
    closed_records = [
        {
            "date": date,
            "restaurant": "DORMITORY",
            "source_slot": "전체",
            "raw_text": "",
            "source_english": (),
            "outcome": "EXPECTED_EMPTY",
            "reason_code": "WEEKEND_CLOSED",
        }
        for date in dates[-2:]
    ]
    closed_by_date = {record["date"]: record for record in closed_records}
    scrape = AsyncMock(
        side_effect=lambda _config, target_date, **_kwargs: (
            [closed_by_date[target_date]]
            if target_date in closed_by_date
            else _complete_raw(target_date, "DORMITORY")
        )
    )
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    assert response["statusCode"] == 200
    assert interpret.await_count == 10
    assert publish.await_count == 20
    assert _date_summary_dates(slack) == dates[:-2]


def test_direct_dormitory_fetches_seven_dates_once_and_aggregates_weekly_response():
    dates = [f"202607{day:02d}" for day in range(13, 20)]
    scrape = AsyncMock(return_value=[_raw(date, "DORMITORY") for date in dates])
    slack = AsyncMock()
    with (
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", AsyncMock(return_value=_accepted())),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_dormitory", "target_date": dates[0]}, _Context()
        )

    config = handler.load_operation_config("scrape_dormitory")
    scrape.assert_awaited_once_with(config, dates[0], requested_dates=dates)
    assert slack.await_count == 7
    assert {call.args[1]["restaurant"] for call in slack.await_args_list} == {"기숙사식당"}
    body = json.loads(response["body"])
    assert body["success"] is True
    assert body["date"] == "20260713_weekly"
    assert body["message"] == "기숙사식당 주간 메뉴 처리 완료 (7일치)"
    assert set(body["menus"]) == {f"{date}_중식1" for date in dates}


def test_parse_event_allowlists_schedule_mode_and_defaults_notify_summary_true():
    assert handler.parse_event({"schedule_mode": "remaining_week"})["schedule_mode"] == "remaining_week"
    assert handler.parse_event({"schedule_mode": "tomorrow"})["schedule_mode"] is None
    assert handler.parse_event({"schedule_mode": "unsafe"})["schedule_mode"] is None
    assert handler.parse_event({"schedule_mode": ["tomorrow"]})["schedule_mode"] is None
    assert handler.parse_event({})["notify_summary"] is True
    assert handler.parse_event({"notify_summary": False})["notify_summary"] is False
    assert handler.parse_event({"notify_summary": "unsafe"})["notify_summary"] is True


def test_remaining_week_schedule_uses_asia_seoul_date_through_restaurant_week_end():
    config = handler.load_operation_config("schedule_haksik")
    assert config is not None
    request = handler.parse_event({"schedule_mode": "remaining_week"})
    fixed_now = datetime(2026, 9, 17, 16, 5, tzinfo=ZoneInfo("Asia/Seoul"))

    with patch.object(handler, "_now_seoul", return_value=fixed_now):
        assert handler._dates_for(config, request) == ["20260917", "20260918"]


def test_schedule_anchor_keeps_next_week_stable_after_retry_crosses_monday():
    config = handler.load_operation_config("schedule_haksik")
    assert config is not None
    request = handler.parse_event(
        {
            "schedule_mode": "next_week",
            "schedule_anchor": "2026-09-20T07:00:00Z",
        }
    )

    assert handler._dates_for(config, request) == [
        "20260921", "20260922", "20260923", "20260924", "20260925"
    ]


def test_quiet_schedule_suppresses_only_date_summary_slack():
    scrape = AsyncMock(return_value=_complete_raw("20260918", "HAKSIK"))
    slack = AsyncMock()
    with (
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", AsyncMock(return_value=_accepted())),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {
                "operation": "schedule_haksik",
                "target_date": "20260918",
                "notify_summary": False,
            },
            _Context(),
        )

    assert response["statusCode"] == 200
    slack.assert_not_awaited()


def test_scheduled_menu_validation_failure_is_retryable_for_any_restaurant():
    error = menu_ai.MenuInterpretationError("unsafe model output", "INVALID_TOOL_CALL")
    with (
        patch.object(handler, "scrape", AsyncMock(return_value=[_raw("20260918", "HAKSIK")])),
        patch.object(handler, "interpret_menu", AsyncMock(side_effect=error)),
        patch.object(handler, "replace_slot", AsyncMock()),
        patch.object(handler, "notify_slack", AsyncMock()) as slack,
    ):
        with pytest.raises(handler.RetryableMenuInterpretationError) as raised:
            handler.lambda_handler(
                {
                    "operation": "schedule_haksik",
                    "trigger": "step_functions",
                    "target_date": "20260918",
                    "schedule_mode": "next_week",
                },
                _Context(),
            )

    assert raised.value.target_date == "20260918"
    assert raised.value.restaurant == "HAKSIK"
    slack.assert_not_awaited()


def test_direct_menu_validation_failure_remains_400_summary():
    error = menu_ai.MenuInterpretationError("unsafe model output", "INVALID_TOOL_CALL")
    with (
        patch.object(handler, "scrape", AsyncMock(return_value=[_raw("20260918", "HAKSIK")])),
        patch.object(handler, "interpret_menu", AsyncMock(side_effect=error)),
        patch.object(handler, "replace_slot", AsyncMock()) as publish,
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_haksik", "target_date": "20260918"}, _Context()
        )

    assert response["statusCode"] == 400
    publish.assert_not_awaited()


def test_scheduled_provider_failure_is_retryable_for_step_functions():
    with (
        patch.object(handler, "scrape", AsyncMock(return_value=[_raw("20260918", "HAKSIK")])),
        patch.object(handler, "interpret_menu", AsyncMock(side_effect=RuntimeError("secret"))),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        with pytest.raises(handler.RetryableMenuInterpretationError) as raised:
            handler.lambda_handler(
                {
                    "operation": "schedule_haksik",
                    "trigger": "step_functions",
                    "target_date": "20260918",
                    "schedule_mode": "next_week",
                },
                _Context(),
            )

    assert raised.value.restaurant == "HAKSIK"
    assert raised.value.reason_code == "PROVIDER_FAILURE"


def test_generic_final_failure_resolves_allowlisted_restaurant_and_schedule_date():
    slack = AsyncMock()
    with (
        patch.object(handler, "notify_slack", slack),
        patch.object(handler, "_week_dates", return_value=["20260921"]),
    ):
        response = handler.lambda_handler(
            {
                "operation": "notify_final_failure",
                "restaurant": "HAKSIK",
                "schedule_mode": "next_week",
                "error_type": "RetryableMenuInterpretationError",
            },
            _Context(),
        )

    assert response["statusCode"] == 200
    assert slack.await_args is not None
    assert slack.await_args.args[0]["slack_webhook_url"] == "https://hooks.slack.test/webhook"
    notification = slack.await_args.args[1]
    assert notification["restaurant"] == "학생식당"
    assert notification["date"] == "20260921"
    assert notification["error_type"] == "RetryableMenuInterpretationError"


def test_scheduled_empty_failure_uses_actual_restaurant_name():
    class SourceError(RuntimeError):
        outcome = "AMBIGUOUS_EMPTY"

    source_error = SourceError("unsafe source detail")
    with (
        patch.object(handler, "scrape", AsyncMock(side_effect=source_error)),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        with pytest.raises(handler.RetryableEmptyMenuError) as raised:
            handler.lambda_handler(
                {
                    "operation": "schedule_haksik",
                    "trigger": "step_functions",
                    "target_date": "20260918",
                    "schedule_mode": "next_week",
                },
                _Context(),
            )

    assert raised.value.restaurant == "HAKSIK"


def test_scheduled_api_failure_uses_actual_restaurant_name():
    with (
        patch.object(handler, "scrape", AsyncMock(return_value=[_raw("20260918", "HAKSIK")])),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", AsyncMock(side_effect=[_accepted(), RuntimeError("unsafe API detail")])),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        with pytest.raises(handler.RetryableApiSendError) as raised:
            handler.lambda_handler(
                {
                    "operation": "schedule_haksik",
                    "trigger": "step_functions",
                    "target_date": "20260918",
                    "schedule_mode": "next_week",
                },
                _Context(),
            )

    assert raised.value.restaurant == "HAKSIK"


def test_notify_summary_false_does_not_suppress_final_failure_slack():
    slack = AsyncMock()
    with patch.object(handler, "notify_slack", slack):
        handler.lambda_handler(
            {
                "operation": "notify_final_failure",
                "target_date": "20260918",
                "notify_summary": False,
                "error_type": "RetryableMenuInterpretationError",
            },
            _Context(),
        )

    slack.assert_awaited_once()


def test_already_present_slot_skips_interpretation_and_post_after_scrape():
    exists = AsyncMock(return_value=[["제육볶음"]])
    scrape = AsyncMock(return_value=[_raw("20260929", "FACULTY")])
    interpret = AsyncMock()
    publish = AsyncMock()
    slack = AsyncMock()

    with (
        patch.object(handler, "existing_meals", exists),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "schedule_faculty", "target_date": "20260929"},
            _Context(),
        )

    assert response["statusCode"] == 200
    scrape.assert_awaited_once()
    interpret.assert_not_awaited()
    publish.assert_not_awaited()
    slack.assert_not_awaited()
    assert {call.args[2] for call in exists.await_args_list} == {"dev", "prod"}


def test_scheduled_summary_is_sent_only_for_the_newly_published_date():
    dates = ["20260928", "20260929"]

    async def existence(_config, _time, _environment, *, target_date):
        return [["제육볶음"]] if target_date == dates[0] else []

    scrape = AsyncMock(
        side_effect=lambda _config, target_date: [_raw(target_date, "FACULTY")]
    )
    slack = AsyncMock()

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "existing_meals", AsyncMock(side_effect=existence)),
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", AsyncMock(return_value=_accepted())),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {"operation": "schedule_faculty", "schedule_mode": "next_week"},
            _Context(),
        )

    assert response["statusCode"] == 200
    assert [call.args[1] for call in scrape.await_args_list] == dates
    assert _date_summary_dates(slack) == [dates[1]]


def test_haksik_existence_check_uses_configured_morning_time_for_dinner_slot():
    exists = AsyncMock(return_value=[["제육볶음"]])

    with (
        patch.object(handler, "existing_meals", exists),
        patch.object(
            handler,
            "scrape",
            AsyncMock(
                return_value=[
                    _raw_slot("20260929", "HAKSIK", "중식1"),
                    _raw_slot("20260929", "HAKSIK", "석식1"),
                ]
            ),
        ),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": "20260929"},
            _Context(),
        )

    checked_times = {call.args[1] for call in exists.await_args_list}
    assert checked_times == {"LUNCH", "MORNING"}


def test_929_incident_reconciles_only_monday_at_0800_then_fills_rest_at_0900():
    dates = ["20260928", "20260929", "20260930", "20261001", "20261002", "20261003", "20261004"]
    monday_records = [
        _raw_slot(dates[0], "DORMITORY", "중식"),
        _raw_slot(dates[0], "DORMITORY", "석식"),
    ]
    full_week_records = [
        _raw_slot(date, "DORMITORY", slot)
        for date in dates
        for slot in ("중식", "석식")
    ]
    records_by_date = {
        date: [record for record in full_week_records if record["date"] == date]
        for date in dates
    }

    async def scrape_date(_config, target_date, **_kwargs):
        if run == 0 and target_date != dates[0]:
            return []
        return records_by_date[target_date]

    scrape = AsyncMock(side_effect=scrape_date)
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()
    run = 0

    async def existence(_config, _time, _environment, *, target_date):
        return [["제육볶음"]] if run == 1 and target_date == dates[0] else []

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "existing_meals", AsyncMock(side_effect=existence)),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        first = handler.lambda_handler(
            {
                "operation": "schedule_dormitory",
                "schedule_mode": "current_week",
                "notify_summary": False,
            },
            _Context(),
        )
        run = 1
        second = handler.lambda_handler(
            {
                "operation": "schedule_dormitory",
                "schedule_mode": "current_week",
                "notify_summary": False,
            },
            _Context(),
        )

    assert first["statusCode"] == second["statusCode"] == 200
    assert scrape.await_count == 14
    assert all(call.kwargs["requested_dates"] == [call.args[1]] for call in scrape.await_args_list)
    assert publish.await_count == 28
    assert interpret.await_count == 14
    slack.assert_not_awaited()
    assert json.loads(second["body"])["remaining_missing"] == []
    assert json.loads(second["body"])["completeness"] == {
        "secured": 14,
        "total": 14,
        "expected_empty": 0,
    }


def test_one_date_publication_failure_does_not_block_later_dates():
    dates = ["20260928", "20260929"]
    present: set[tuple[str, str]] = set()
    failed_once = False
    scrape = AsyncMock(
        side_effect=lambda _config, target_date: [_raw(target_date, "FACULTY")]
    )

    async def existence(_config, time_slot, environment, *, target_date):
        return [["제육볶음"]] if (target_date, environment) in present else []

    async def publication(_config, target_date, _time, _items, environment):
        nonlocal failed_once
        key = (target_date, environment)
        if key == (dates[0], "prod") and not failed_once:
            failed_once = True
            raise RuntimeError("prod unavailable")
        present.add(key)
        return _accepted()

    publish = AsyncMock(side_effect=publication)

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "existing_meals", AsyncMock(side_effect=existence)),
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        with pytest.raises(handler.RetryableApiSendError):
            handler.lambda_handler(
                {
                    "operation": "schedule_faculty",
                    "trigger": "step_functions",
                    "schedule_mode": "next_week",
                    "notify_summary": False,
                },
                _Context(),
            )
        retry = handler.lambda_handler(
            {
                "operation": "schedule_faculty",
                "trigger": "step_functions",
                "schedule_mode": "next_week",
                "notify_summary": False,
            },
            _Context(),
        )

    assert [call.args[1] for call in scrape.await_args_list] == [*dates, *dates]
    assert publish.await_count == 5
    assert json.loads(retry["body"])["remaining_missing"] == []


@pytest.mark.parametrize(("retry_count", "alerts", "raises"), [(8, 0, True), (9, 1, False)])
def test_general_restaurant_alerts_only_when_retry_cap_is_exhausted(
    retry_count, alerts, raises
):
    slack = AsyncMock()

    def invoke():
        return handler.lambda_handler(
            {
                "operation": "schedule_faculty",
                "trigger": "step_functions",
                "target_date": "20260929",
                "retry_count": retry_count,
                "schedule_mode": "next_week",
                "notify_summary": True,
            },
            _Context(),
        )

    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", AsyncMock(return_value=[])),
        patch.object(handler, "notify_slack", slack),
    ):
        if raises:
            with pytest.raises(handler.RetryableEmptyMenuError):
                invoke()
        else:
            response = invoke()
            assert response["statusCode"] == 200

    assert slack.await_count == alerts
    if alerts:
        assert slack.await_args is not None
        assert slack.await_args.args[1]["type"] == "weekly_completeness"


@pytest.mark.parametrize("notify_summary", [False, True])
def test_dormitory_missing_slots_alert_only_on_deadline(notify_summary):
    dates = ["20260928", "20260929"]
    slack = AsyncMock()
    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(
            handler,
            "_now_seoul",
            return_value=datetime(2026, 9, 28, 16, 5, tzinfo=ZoneInfo("Asia/Seoul")),
        ),
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", AsyncMock(return_value=[])),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {
                "operation": "schedule_dormitory",
                "schedule_mode": "current_week",
                "notify_summary": notify_summary,
            },
            _Context(),
        )

    assert response["statusCode"] == 200
    assert slack.await_count == int(notify_summary)
    if notify_summary:
        assert slack.await_args is not None
        assert slack.await_args.args[1]["type"] == "weekly_completeness"


@pytest.mark.parametrize("operation", ["scrape_faculty", "schedule_faculty"])
def test_get_failure_blocks_post_for_manual_and_scheduled_paths(operation):
    publish = AsyncMock()
    with (
        patch.object(handler, "existing_meals", AsyncMock(side_effect=RuntimeError("GET failed"))),
        patch.object(
            handler,
            "scrape",
            AsyncMock(return_value=[_raw("20260929", "FACULTY")]),
        ),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {
                "operation": operation,
                "target_date": "20260929",
                "schedule_mode": "remaining_week",
            },
            _Context(),
        )

    publish.assert_not_awaited()
    assert response["statusCode"] in {200, 400}


def test_manual_present_slot_skips_interpretation_and_post():
    interpret = AsyncMock()
    publish = AsyncMock()
    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=[["제육볶음"]])),
        patch.object(
            handler,
            "scrape",
            AsyncMock(return_value=[_raw("20260929", "FACULTY")]),
        ),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_faculty", "target_date": "20260929"},
            _Context(),
        )

    assert response["statusCode"] == 200
    interpret.assert_not_awaited()
    publish.assert_not_awaited()


def test_source_http_failure_isolated_per_date_and_later_date_publishes():
    class SourceHttpError(RuntimeError):
        outcome = "API_FAILURE"

    dates = ["20260928", "20260929"]
    scrape = AsyncMock(
        side_effect=[SourceHttpError("source 500"), [_raw(dates[1], "FACULTY")]]
    )
    publish = AsyncMock(return_value=_accepted())
    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(
            handler,
            "_now_seoul",
            return_value=datetime(2026, 9, 28, 16, 5, tzinfo=ZoneInfo("Asia/Seoul")),
        ),
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {
                "operation": "schedule_faculty",
                "schedule_mode": "remaining_week",
                "notify_summary": False,
            },
            _Context(),
        )

    assert response["statusCode"] == 200
    assert scrape.await_count == 2
    assert {call.args[1] for call in publish.await_args_list} == {dates[1]}
    assert {item["date"] for item in json.loads(response["body"])["remaining_missing"]} == {
        dates[0]
    }


@pytest.mark.parametrize(
    ("operation", "schedule_mode"),
    [("schedule_faculty", "remaining_week"), ("schedule_dormitory", "current_week")],
)
def test_recovery_and_dormitory_missing_slots_do_not_raise_retryable(
    operation, schedule_mode
):
    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", AsyncMock(return_value=[])),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {
                "operation": operation,
                "target_date": "20260929",
                "schedule_mode": schedule_mode,
                "notify_summary": False,
            },
            _Context(),
        )

    assert response["statusCode"] == 200


def test_dormitory_deadline_alert_contains_only_today_missing_slots():
    dates = ["20260928", "20260929", "20260930"]
    slack = AsyncMock()
    fixed_now = datetime(2026, 9, 29, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    with (
        patch.object(handler, "_now_seoul", return_value=fixed_now),
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", AsyncMock(return_value=[])),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {
                "operation": "schedule_dormitory",
                "schedule_mode": "current_week",
                "notify_summary": True,
            },
            _Context(),
        )

    assert response["statusCode"] == 200
    slack.assert_awaited_once()
    assert slack.await_args is not None
    missing = slack.await_args.args[1]["remaining_missing"]
    assert {item["date"] for item in missing} == {"20260929"}
    assert json.loads(response["body"])["completeness"]["total"] == 4


def test_next_week_retry_crossing_midnight_sets_delayed_schedule_and_same_week():
    config = handler.load_operation_config("schedule_haksik")
    assert config is not None
    monday = datetime(2026, 9, 21, 0, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    event = {
        "schedule_mode": "next_week",
        "schedule_anchor": "2026-09-20T07:00:00Z",
        "retry_count": 4,
        "delayed_schedule": False,
    }

    with patch.object(handler, "_now_seoul", return_value=monday):
        request = handler.parse_event(event)
        dates = handler._dates_for(config, request)

    assert request["delayed_schedule"] is True
    assert request["schedule_mode"] == "current_week"
    assert dates == ["20260921", "20260922", "20260923", "20260924", "20260925"]


def test_step_functions_retry_after_midnight_keeps_retrying_original_week():
    monday = datetime(2026, 9, 21, 0, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    with (
        patch.object(handler, "_now_seoul", return_value=monday),
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", AsyncMock(return_value=[])),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        with pytest.raises(handler.RetryableEmptyMenuError) as raised:
            handler.lambda_handler(
                {
                    "operation": "schedule_haksik",
                    "trigger": "step_functions",
                    "schedule_mode": "next_week",
                    "schedule_anchor": "2026-09-20T07:00:00Z",
                    "retry_count": 4,
                    "delayed_schedule": True,
                    "notify_summary": True,
                },
                _Context(),
            )

    assert raised.value.target_date == "20260921"


@pytest.mark.parametrize(
    ("existing", "expected_new"),
    [
        ([], 3),
        ([['제육볶음', '쌀밥']], 2),
        ([['제육볶음'], ['돈까스'], ['비빔밥']], 0),
    ],
)
def test_same_time_corners_publish_only_uncovered_corners(existing, expected_new):
    date = "20261006"
    interpret = AsyncMock(
        side_effect=[
            {"menuNames": [f"신규메뉴{index}"], "mainMenus": []}
            for index in range(expected_new)
        ]
    )
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()

    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=existing), create=True),
        patch.object(handler, "scrape", AsyncMock(return_value=_haksik_lunch_corners(date))),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler(
            {
                "operation": "schedule_haksik",
                "target_date": date,
                "schedule_mode": "remaining_week",
            },
            _Context(),
        )

    assert interpret.await_count == expected_new
    assert publish.await_count == (2 if expected_new else 0)
    body = json.loads(response["body"])
    assert body["completeness"] == {
        "secured": 3,
        "total": 3,
        "expected_empty": 0,
    }
    assert body["remaining_missing"] == []
    assert _date_summary_dates(slack) == ([date] if expected_new else [])


def test_existing_raw_menu_is_not_reposted_when_fresh_llm_would_differ():
    date = "20261006"
    interpret = AsyncMock(
        return_value={"menuNames": ["제육볶음 정식"], "mainMenus": []}
    )
    publish = AsyncMock()
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(return_value=[["제육볶음", "쌀밥"]]),
            create=True,
        ),
        patch.object(
            handler,
            "scrape",
            AsyncMock(return_value=[_haksik_lunch_corners(date)[0]]),
        ),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    interpret.assert_not_awaited()
    publish.assert_not_awaited()


def test_corner_get_failure_blocks_all_posts_for_that_time():
    date = "20261006"
    publish = AsyncMock()
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(side_effect=RuntimeError("GET failed")),
            create=True,
        ),
        patch.object(handler, "scrape", AsyncMock(return_value=_haksik_lunch_corners(date))),
        patch.object(handler, "interpret_menu", AsyncMock()),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    publish.assert_not_awaited()
    assert len(json.loads(response["body"])["remaining_missing"]) == 3


def test_manual_target_date_uses_corner_level_existing_meal_assignment():
    date = "20261006"
    interpret = AsyncMock()
    publish = AsyncMock()
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(return_value=[["제육볶음"], ["돈까스"], ["비빔밥"]]),
            create=True,
        ),
        patch.object(handler, "scrape", AsyncMock(return_value=_haksik_lunch_corners(date))),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_haksik", "target_date": date}, _Context()
        )

    assert response["statusCode"] == 200
    interpret.assert_not_awaited()
    publish.assert_not_awaited()


def test_ascii_variant_in_raw_text_still_covers_existing_korean_meal():
    date = "20261006"
    raw = {
        **_raw_slot(date, "HAKSIK", "중식1"),
        "raw_text": "등촌st샤브칼국수 포자만두 미니밥 배추김치",
    }
    interpret = AsyncMock()
    publish = AsyncMock()
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(
                return_value=[
                    ["등촌샤브칼국수", "포자만두", "미니밥", "배추김치"]
                ]
            ),
        ),
        patch.object(handler, "scrape", AsyncMock(return_value=[raw])),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    interpret.assert_not_awaited()
    publish.assert_not_awaited()


def test_greedy_assignment_uses_distinct_mains_and_posts_missing_corner():
    date = "20261006"
    corners = [
        {**_raw_slot(date, "HAKSIK", "중식1"), "raw_text": "제육볶음 가쓰오장국 배추김치"},
        {**_raw_slot(date, "HAKSIK", "중식2"), "raw_text": "돈까스 가쓰오장국 배추김치"},
        {**_raw_slot(date, "HAKSIK", "중식3"), "raw_text": "비빔밥 가쓰오장국 배추김치"},
    ]
    interpret = AsyncMock(return_value={"menuNames": ["비빔밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(
                return_value=[
                    ["돈까스", "가쓰오장국", "배추김치"],
                    ["제육볶음", "가쓰오장국", "배추김치"],
                ]
            ),
        ),
        patch.object(handler, "scrape", AsyncMock(return_value=corners)),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    interpret.assert_awaited_once()
    assert interpret.await_args is not None
    assert interpret.await_args.args[1]["source_slot"] == "중식3"
    assert publish.await_count == 2


def test_existing_meal_below_half_score_does_not_cover_corner():
    date = "20261006"
    raw = {**_raw_slot(date, "HAKSIK", "중식1"), "raw_text": "제육볶음 쌀밥"}
    interpret = AsyncMock(return_value={"menuNames": ["제육볶음", "쌀밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(return_value=[["제육볶음", "가쓰오장국", "배추김치"]]),
        ),
        patch.object(handler, "scrape", AsyncMock(return_value=[raw])),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", publish),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    interpret.assert_awaited_once()
    assert publish.await_count == 2


def _slot_result(*, meal_ids=(1,), deleted=(), kept=(), unmatched=()):
    return SimpleNamespace(
        meal_ids=meal_ids,
        unmatched_main_menus=unmatched,
        deleted_meal_ids=deleted,
        kept_with_reviews=kept,
    )


def test_fill_one_missing_corner_puts_full_slot_and_interprets_only_missing():
    date = "20261006"
    interpret = AsyncMock(return_value={"menuNames": ["비빔밥"], "mainMenus": []})
    replace = AsyncMock(return_value=_slot_result(meal_ids=(1, 2, 3)))
    existing = [["제육볶음"], ["돈까스"]]
    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=existing)),
        patch.object(handler, "scrape", AsyncMock(return_value=_haksik_lunch_corners(date))),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    interpret.assert_awaited_once()
    assert replace.await_count == 2
    for call in replace.await_args_list:
        assert [item["menuNames"] for item in call.args[3]] == [
            ["제육볶음"],
            ["돈까스"],
            ["비빔밥"],
        ]
        assert [item["mainMenus"] for item in call.args[3]] == [None, None, []]


def test_fill_changed_menu_replaces_full_slot():
    date = "20261006"
    raw = {**_raw_slot(date, "HAKSIK", "중식1"), "raw_text": "새우볶음밥"}
    replace = AsyncMock(return_value=_slot_result(meal_ids=(2,), deleted=(1,)))
    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=[["제육볶음"]])),
        patch.object(handler, "scrape", AsyncMock(return_value=[raw])),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["새우볶음밥"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    assert replace.await_count == 2
    assert replace.await_args_list[0].args[3][0]["menuNames"] == ["새우볶음밥"]


def test_force_interprets_every_corner_once_and_reuses_for_both_environments():
    date = "20261006"
    interpret = AsyncMock(
        side_effect=[
            {"menuNames": ["제육볶음"], "mainMenus": []},
            {"menuNames": ["돈까스"], "mainMenus": []},
            {"menuNames": ["비빔밥"], "mainMenus": []},
        ]
    )
    replace = AsyncMock(return_value=_slot_result(meal_ids=(1, 2, 3)))
    with (
        patch.object(
            handler,
            "existing_meals",
            AsyncMock(return_value=[["제육볶음"], ["돈까스"], ["비빔밥"]]),
        ),
        patch.object(handler, "scrape", AsyncMock(return_value=_haksik_lunch_corners(date))),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {
                "operation": "schedule_haksik",
                "target_date": date,
                "publish_mode": "force",
            },
            _Context(),
        )

    assert interpret.await_count == 3
    assert replace.await_count == 2
    assert replace.await_args_list[0].args[3] == replace.await_args_list[1].args[3]


def test_slot_get_failure_prevents_put_for_failed_environment():
    date = "20261006"

    async def get_existing(_config, _time, environment, **_kwargs):
        if environment == "prod":
            raise RuntimeError("GET failed")
        return []

    replace = AsyncMock(return_value=_slot_result())
    with (
        patch.object(handler, "existing_meals", AsyncMock(side_effect=get_existing)),
        patch.object(handler, "scrape", AsyncMock(return_value=[_haksik_lunch_corners(date)[0]])),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["제육볶음"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    assert [call.args[4] for call in replace.await_args_list] == ["dev"]


def test_all_expected_empty_never_puts_slot():
    date = "20261006"
    closed = {
        **_raw_slot(date, "HAKSIK", "중식1"),
        "raw_text": "미운영",
        "outcome": "EXPECTED_EMPTY",
        "reason_code": "CLOSED_MARKER",
    }
    replace = AsyncMock()
    with (
        patch.object(handler, "scrape", AsyncMock(return_value=[closed])),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    replace.assert_not_awaited()


def test_force_skips_past_date_without_llm_or_put():
    past = "20260901"
    interpret = AsyncMock()
    replace = AsyncMock()
    now = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    with (
        patch.object(handler, "_now_seoul", return_value=now),
        patch.object(handler, "scrape", AsyncMock(return_value=_haksik_lunch_corners(past))),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler(
            {
                "operation": "schedule_haksik",
                "target_date": past,
                "publish_mode": "force",
            },
            _Context(),
        )

    interpret.assert_not_awaited()
    replace.assert_not_awaited()


def test_kept_with_reviews_sends_slot_warning():
    date = "20261006"
    replace = AsyncMock(
        return_value=_slot_result(meal_ids=(2,), deleted=(1,), kept=(99,))
    )
    slack = AsyncMock()
    with (
        patch.object(handler, "existing_meals", AsyncMock(return_value=[])),
        patch.object(handler, "scrape", AsyncMock(return_value=[_haksik_lunch_corners(date)[0]])),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["제육볶음"], "mainMenus": []}),
        ),
        patch.object(handler, "replace_slot", replace, create=True),
        patch.object(handler, "notify_slack", slack),
    ):
        handler.lambda_handler(
            {"operation": "schedule_haksik", "target_date": date}, _Context()
        )

    warnings = [
        call.args[1]
        for call in slack.await_args_list
        if call.args[1]["type"] == "kept_with_reviews"
    ]
    assert warnings
    assert warnings[0]["time"] == "LUNCH"
    assert warnings[0]["meal_ids"] == [99]


def test_parse_event_defaults_fill_and_accepts_force_publish_mode():
    assert handler.parse_event({})["publish_mode"] == "fill"
    assert handler.parse_event({"publish_mode": "force"})["publish_mode"] == "force"
    assert handler.parse_event({"publish_mode": "unsafe"})["publish_mode"] == "fill"
