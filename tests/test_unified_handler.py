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


def _raw(date: str, restaurant: str) -> dict[str, str]:
    slot = "석식1" if restaurant == "HAKSIK" else "중식1"
    return {
        "date": date,
        "restaurant": restaurant,
        "source_slot": slot,
        "raw_text": "제육볶음 Pork",
    }


def _accepted(unmatched=None, warnings=None):
    return SimpleNamespace(
        accepted=True,
        unmatched_main_menus=unmatched or [],
        warnings=warnings or [],
    )


def _dependencies(entry):
    restaurant = entry["restaurant"]
    dates = entry.get("result_dates", entry.get("current_dates", [entry.get("expected_date", "20260713")]))
    if restaurant == "DORMITORY":
        scrape = AsyncMock(return_value=[_raw(date, restaurant) for date in dates])
    else:
        scrape = AsyncMock(
            side_effect=lambda _config, target_date: [_raw(target_date, restaurant)]
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
        patch.object(handler, "publish_menu", publish),
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
    actual_environments = [call.args[2] for call in publish.await_args_list]
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
        patch.object(handler, "publish_menu", publish),
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
        patch.object(handler, "publish_menu", publish),
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
        patch.object(handler, "publish_menu", AsyncMock()),
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
    scrape = AsyncMock(return_value=[_raw("20260713", "DORMITORY")])
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(side_effect=[_accepted(), RuntimeError("prod unavailable")])
    slack = AsyncMock()

    with (
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "publish_menu", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        with pytest.raises(handler.RetryableApiSendError) as raised:
            handler.lambda_handler(
                {"operation": "schedule_dormitory", "target_date": "20260713"},
                _Context(),
            )

    assert raised.value.target_date == "20260713"
    assert raised.value.failed_days == 1
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
        patch.object(handler, "publish_menu", AsyncMock()) as publish,
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
        patch.object(handler, "publish_menu", boundaries[2]),
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
        patch.object(handler, "publish_menu", publish),
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
        patch.object(handler, "publish_menu", publish),
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
        patch.object(handler, "publish_menu", publish),
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
        patch.object(handler, "publish_menu", publish),
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


def test_partial_dormitory_week_retries_before_ai_spring_or_slack():
    dates = [f"202607{day:02d}" for day in range(13, 20)]
    scrape = AsyncMock(
        return_value=[_raw(date, "DORMITORY") for date in dates if date != dates[2]]
    )
    interpret = AsyncMock()
    publish = AsyncMock()
    slack = AsyncMock()

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "publish_menu", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        with pytest.raises(handler.RetryableEmptyMenuError) as raised:
            handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    assert raised.value.target_date == dates[0]
    interpret.assert_not_awaited()
    publish.assert_not_awaited()
    slack.assert_not_awaited()


def test_complete_dormitory_week_including_closed_date_keeps_current_behavior():
    dates = [f"202607{day:02d}" for day in range(13, 20)]
    closed_record = {
        "date": dates[-1],
        "restaurant": "DORMITORY",
        "source_slot": "중식1",
        "raw_text": "미운영",
        "source_english": (),
        "outcome": "EXPECTED_EMPTY",
        "reason_code": "CLOSED_MARKER",
    }
    scrape = AsyncMock(
        return_value=[_raw(date, "DORMITORY") for date in dates[:-1]] + [closed_record]
    )
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()
    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "publish_menu", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    scrape.assert_awaited_once_with(
        handler.load_operation_config("schedule_dormitory"),
        dates[0],
        requested_dates=dates,
    )
    assert response["statusCode"] == 200
    assert interpret.await_count == 6
    assert publish.await_count == 12
    assert slack.await_count == 7
    assert {call.args[1]["restaurant"] for call in slack.await_args_list} == {"기숙사식당"}


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
    scrape = AsyncMock(
        return_value=[_raw(date, "DORMITORY") for date in dates[:5]] + closed_records
    )
    interpret = AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []})
    publish = AsyncMock(return_value=_accepted())
    slack = AsyncMock()

    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(handler, "interpret_menu", interpret),
        patch.object(handler, "publish_menu", publish),
        patch.object(handler, "notify_slack", slack),
    ):
        response = handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    assert response["statusCode"] == 200
    assert interpret.await_count == 5
    assert publish.await_count == 10
    assert slack.await_count == 7
    weekend_notifications = [call.args[1] for call in slack.await_args_list[-2:]]
    assert all(item["menus"] == {"전체": []} for item in weekend_notifications)
    assert all(
        item["empty_reasons"] == {"전체": "WEEKEND_CLOSED"}
        for item in weekend_notifications
    )


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
        patch.object(handler, "publish_menu", AsyncMock(return_value=_accepted())),
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
    assert handler.parse_event({"schedule_mode": "tomorrow"})["schedule_mode"] == "tomorrow"
    assert handler.parse_event({"schedule_mode": "unsafe"})["schedule_mode"] is None
    assert handler.parse_event({"schedule_mode": ["tomorrow"]})["schedule_mode"] is None
    assert handler.parse_event({})["notify_summary"] is True
    assert handler.parse_event({"notify_summary": False})["notify_summary"] is False
    assert handler.parse_event({"notify_summary": "unsafe"})["notify_summary"] is True


def test_tomorrow_schedule_uses_asia_seoul_date():
    config = handler.load_operation_config("schedule_haksik")
    assert config is not None
    request = handler.parse_event({"schedule_mode": "tomorrow"})
    fixed_now = datetime(2026, 9, 17, 23, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    with patch.object(handler, "_now_seoul", return_value=fixed_now):
        assert handler._dates_for(config, request) == ["20260918"]


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
    scrape = AsyncMock(return_value=[_raw("20260918", "HAKSIK")])
    slack = AsyncMock()
    with (
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "publish_menu", AsyncMock(return_value=_accepted())),
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
        patch.object(handler, "publish_menu", AsyncMock()),
        patch.object(handler, "notify_slack", AsyncMock()) as slack,
    ):
        with pytest.raises(handler.RetryableMenuInterpretationError) as raised:
            handler.lambda_handler(
                {"operation": "schedule_haksik", "target_date": "20260918"},
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
        patch.object(handler, "publish_menu", AsyncMock()) as publish,
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
                {"operation": "schedule_haksik", "target_date": "20260918"},
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
                {"operation": "schedule_haksik", "target_date": "20260918"},
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
        patch.object(
            handler,
            "publish_menu",
            AsyncMock(side_effect=[_accepted(), RuntimeError("unsafe API detail")]),
        ),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        with pytest.raises(handler.RetryableApiSendError) as raised:
            handler.lambda_handler(
                {"operation": "schedule_haksik", "target_date": "20260918"},
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
