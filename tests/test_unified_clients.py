import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from tenacity import wait_none

from functions.clients import (
    SlackNotificationError,
    SpringPublishError,
    publish_spring_meal,
    send_slack_text,
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
@pytest.mark.parametrize(
    ("fixture_name", "expected_unmatched", "expects_warning"),
    [
        ("accepted_matched", (), False),
        (
            "accepted_unmatched",
            ({"nameKo": "없는메뉴", "nameEn": "Missing"},),
            False,
        ),
        ("accepted_empty", (), False),
        ("accepted_malformed", (), True),
    ],
)
async def test_spring_accepted_responses_are_never_retried(
    fixture_name, expected_unmatched, expects_warning
):
    fixture = FIXTURE["responses"][fixture_name]
    session = _session_with_response(_response(fixture["status"], fixture["body"]))

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        result = await publish_spring_meal(**_spring_arguments())

    assert result.accepted is True
    assert result.unmatched_main_menus == expected_unmatched
    assert bool(result.warnings) is expects_warning
    session.post.assert_called_once()
    assert session.post.call_args.args == ("https://spring.example/meals/with-price",)
    assert session.post.call_args.kwargs["params"] == REQUEST["query"]
    assert session.post.call_args.kwargs["json"] == REQUEST["body"]
    assert session.post.call_args.kwargs["timeout"].total == REQUEST["timeout_seconds"]


@pytest.mark.asyncio
async def test_spring_includes_only_validated_non_empty_main_menus():
    session = _session_with_response(_response(200, {"unmatchedMainMenus": []}))
    main_menus = [{"nameKo": "제육볶음", "nameEn": "Spicy Pork"}]

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        await publish_spring_meal(**_spring_arguments(main_menus=main_menus))

    assert session.post.call_args.kwargs["json"] == {
        **REQUEST["body"],
        "mainMenus": main_menus,
    }

    with pytest.raises(ValueError, match="validated and non-empty"):
        await publish_spring_meal(
            **_spring_arguments(
                main_menus=[{"nameKo": "없는메뉴", "nameEn": "Missing"}]
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "transport"])
async def test_spring_retries_non_2xx_and_transport_failures_three_times(failure):
    session = _session_with_response(_response(500, {"message": "server error"}))
    if failure == "transport":
        session.post.side_effect = aiohttp.ClientConnectionError("offline")
    publish_without_wait = cast(Any, publish_spring_meal).retry_with(wait=wait_none())

    with patch("functions.clients.aiohttp.ClientSession", return_value=session):
        with pytest.raises(SpringPublishError):
            await publish_without_wait(**_spring_arguments())

    assert session.post.call_count == 3


@pytest.mark.asyncio
async def test_slack_retries_independently_without_repeating_accepted_spring_post():
    spring_session = _session_with_response(
        _response(200, {"unmatchedMainMenus": []})
    )
    with patch("functions.clients.aiohttp.ClientSession", return_value=spring_session):
        spring_result = await publish_spring_meal(**_spring_arguments())

    slack_session = _session_with_response(_response(500, "failed"))
    slack_without_wait = cast(Any, send_slack_text).retry_with(wait=wait_none())
    with patch("functions.clients.aiohttp.ClientSession", return_value=slack_session):
        with pytest.raises(SlackNotificationError):
            await slack_without_wait(
                webhook_url="https://hooks.slack.test/secret",
                text="publication accepted",
            )

    assert spring_result.accepted is True
    assert spring_session.post.call_count == 1
    assert slack_session.post.call_count == 3
    assert slack_session.post.call_args.kwargs["json"] == {
        "username": "학식봇",
        "text": "publication accepted",
        "icon_emoji": ":fork_and_knife:",
    }
    assert slack_session.post.call_args.kwargs["timeout"].total == 10


def test_retry_policy_remains_three_attempts_with_two_second_waits():
    for function in (publish_spring_meal, send_slack_text):
        retry_policy = cast(Any, function).retry
        assert retry_policy.stop.max_attempt_number == 3
        assert retry_policy.wait.wait_fixed == 2
