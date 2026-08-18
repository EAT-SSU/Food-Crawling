import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from functions import handler  # pyright: ignore[reportAttributeAccessIssue]


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
        {"slot": "중식1", "reason": "unmatched main menus", "items": unmatched}
    ]


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


def test_dormitory_schedule_fetches_full_week_once():
    dates = [f"202607{day:02d}" for day in range(13, 20)]
    scrape = AsyncMock(return_value=[_raw(date, "DORMITORY") for date in dates])
    with (
        patch.object(handler, "_week_dates", return_value=dates),
        patch.object(handler, "scrape", scrape),
        patch.object(
            handler,
            "interpret_menu",
            AsyncMock(return_value={"menuNames": ["밥"], "mainMenus": []}),
        ),
        patch.object(handler, "publish_menu", AsyncMock(return_value=_accepted())),
        patch.object(handler, "notify_slack", AsyncMock()),
    ):
        handler.lambda_handler({"operation": "schedule_dormitory"}, _Context())

    scrape.assert_awaited_once_with(
        handler.load_operation_config("schedule_dormitory"),
        dates[0],
        requested_dates=dates,
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
    body = json.loads(response["body"])
    assert body["success"] is True
    assert body["date"] == "20260713_weekly"
    assert body["message"] == "기숙사식당 주간 메뉴 처리 완료 (7일치)"
    assert set(body["menus"]) == {f"{date}_중식1" for date in dates}
