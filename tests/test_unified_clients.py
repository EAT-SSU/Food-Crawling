import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from tenacity import wait_none

from functions import clients as clients_module
from functions.clients import (
    SpringExistenceError,
    SlackNotificationError,
    SpringSlotReplaceError,
    replace_spring_slot,
    send_slack_text,
    spring_existing_meals,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/characterization/spring_responses.json").read_text(
        encoding="utf-8"
    )
)
REQUEST = FIXTURE["request"]


def _response(status, body):
    response = MagicMock(status=status)
    response.text = AsyncMock(
        return_value="" if body is None else body if isinstance(body, str) else json.dumps(body)
    )
    return response


def _session_with_response(response):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    response_context = MagicMock()
    response_context.__aenter__ = AsyncMock(return_value=response)
    response_context.__aexit__ = AsyncMock(return_value=None)
    session.post.return_value = response_context
    session.put.return_value = response_context
    session.get.return_value = response_context
    return session


def _spring_arguments(**overrides: object) -> dict[str, Any]:
    arguments = {
        "base_url": "https://spring.example/",
        "environment": "dev",
        "date": REQUEST["query"]["date"],
        "restaurant": REQUEST["query"]["restaurant"],
        "time": REQUEST["query"]["time"],
        "menu_names": REQUEST["body"]["menuNames"],
        "price": REQUEST["body"]["price"],
    }
    arguments.update(overrides)
    return arguments


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "transport"])
async def test_slot_put_retries_non_2xx_and_transport_failures_three_times(failure):
    session = _session_with_response(_response(500, {"message": "server error"}))
    if failure == "transport":
        session.put.side_effect = aiohttp.ClientConnectionError("offline")
    replace_without_wait = cast(Any, replace_spring_slot).retry_with(wait=wait_none())

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        with pytest.raises(SpringSlotReplaceError):
            await replace_without_wait(
                base_url="https://spring.example",
                environment="prod",
                date="20261005",
                restaurant="HAKSIK",
                time="LUNCH",
                items=[{"menuNames": ["밥"], "price": 5000, "mainMenus": []}],
            )

    assert session.put.call_count == 3


@pytest.mark.asyncio
async def test_slack_retries_independently_without_repeating_accepted_slot_put():
    spring_session = _session_with_response(
        _response(
            200,
            {
                "isSuccess": True,
                "result": {
                    "mealIds": [1],
                    "unmatchedMainMenus": [[]],
                    "deletedMealIds": [],
                    "keptWithReviews": [],
                },
            },
        )
    )
    with patch("functions.clients.aiohttp.ClientSession", return_value=spring_session):
        spring_result = await replace_spring_slot(
            base_url="https://spring.example",
            environment="prod",
            date="20261005",
            restaurant="HAKSIK",
            time="LUNCH",
            items=[{"menuNames": ["밥"], "price": 5000, "mainMenus": []}],
        )

    slack_session = _session_with_response(_response(500, "failed"))
    slack_without_wait = cast(Any, send_slack_text).retry_with(wait=wait_none())
    with patch("functions.clients.aiohttp.ClientSession", return_value=slack_session):
        with pytest.raises(SlackNotificationError):
            await slack_without_wait(
                webhook_url="https://hooks.slack.test/secret",
                text="publication accepted",
            )

    assert spring_result.meal_ids == (1,)
    assert spring_session.put.call_count == 1
    assert slack_session.post.call_count == 3
    assert slack_session.post.call_args.kwargs["json"] == {
        "username": "학식봇",
        "text": "publication accepted",
        "icon_emoji": ":fork_and_knife:",
    }
    assert slack_session.post.call_args.kwargs["timeout"].total == 10


def test_retry_policy_remains_three_attempts_with_two_second_waits():
    for function in (spring_existing_meals, replace_spring_slot, send_slack_text):
        retry_policy = cast(Any, function).retry
        assert retry_policy.stop.max_attempt_number == 3
        assert retry_policy.wait.wait_fixed == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [([], []), ([{"briefMenus": [{"name": "밥"}]}], [["밥"]])],
)
async def test_spring_existing_meals_uses_get_with_korean_language(result, expected):
    session = _session_with_response(
        _response(200, {"isSuccess": True, "result": result})
    )

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        meals = await spring_existing_meals(
            base_url="https://spring.example/",
            environment="prod",
            date="20260929",
            restaurant="HAKSIK",
            time="MORNING",
        )

    assert meals == expected
    session.get.assert_called_once_with(
        "https://spring.example/meals",
        params={
            "date": "20260929",
            "restaurant": "HAKSIK",
            "time": "MORNING",
            "language": "KO",
        },
        timeout=session.get.call_args.kwargs["timeout"],
    )
    assert session.get.call_args.kwargs["timeout"].total == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _response(500, {"message": "server error"}),
        _response(200, "not-json"),
        _response(200, {"isSuccess": True, "result": "invalid"}),
    ],
)
async def test_spring_existence_check_fails_closed_and_retries(response):
    session = _session_with_response(response)
    exists_without_wait = cast(Any, spring_existing_meals).retry_with(wait=wait_none())

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        with pytest.raises(SpringExistenceError):
            await exists_without_wait(
                base_url="https://spring.example",
                environment="prod",
                date="20260929",
                restaurant="DORMITORY",
                time="LUNCH",
            )

    assert session.get.call_count == 3


@pytest.mark.asyncio
async def test_spring_existing_meals_returns_menu_names_in_result_order():
    assert hasattr(clients_module, "spring_existing_meals")
    session = _session_with_response(
        _response(
            200,
            {
                "isSuccess": True,
                "result": [
                    {"briefMenus": [{"name": "제육볶음"}, {"name": "쌀밥"}]},
                    {"briefMenus": [{"name": "돈까스"}]},
                ],
            },
        )
    )

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        result = await clients_module.spring_existing_meals(
            base_url="https://spring.example",
            environment="prod",
            date="20261005",
            restaurant="HAKSIK",
            time="LUNCH",
        )

    assert result == [["제육볶음", "쌀밥"], ["돈까스"]]


@pytest.mark.asyncio
async def test_replace_spring_slot_puts_full_ordered_slot_and_parses_result():
    assert hasattr(clients_module, "replace_spring_slot")
    session = _session_with_response(
        _response(
            200,
            {
                "isSuccess": True,
                "result": {
                    "mealIds": [11, 12],
                    "unmatchedMainMenus": [[], [{"nameKo": "돈까스"}]],
                    "deletedMealIds": [9],
                    "keptWithReviews": [8],
                },
            },
        )
    )
    items = [
        {"menuNames": ["제육볶음"], "price": 5000, "mainMenus": None},
        {"menuNames": ["돈까스"], "price": 5000, "mainMenus": []},
    ]

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        result = await clients_module.replace_spring_slot(
            base_url="https://spring.example",
            environment="prod",
            date="20261005",
            restaurant="HAKSIK",
            time="LUNCH",
            items=items,
        )

    session.put.assert_called_once()
    assert session.put.call_args.args == (
        "https://spring.example/meals/with-price/slot",
    )
    assert session.put.call_args.kwargs["json"] == items
    assert result.meal_ids == (11, 12)
    assert result.deleted_meal_ids == (9,)
    assert result.kept_with_reviews == (8,)
