import io
import json
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import wait_none

from functions.shared.models.exceptions import MenuPostException
from functions.shared.models.model import ProcessingOutcome, RawMenuData, RestaurantType, TimeSlot
from functions.shared.observability import initialize_observation_logger
from functions.shared.repositories.clients.gpt_client import GPTClient
from functions.shared.repositories.clients.slack_client import SlackClient
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient


SOURCE_SECRET = "중식 SECRET_TOKEN"


def _events(output: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.getvalue().splitlines()]


def _gpt_response(menus: list[str], request_id: str = "request-safe-id") -> SimpleNamespace:
    tool_call = SimpleNamespace(
        function=SimpleNamespace(arguments=json.dumps({"all_menus": menus}))
    )
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(id=request_id, choices=[SimpleNamespace(message=message)])


def _gpt_client(create: AsyncMock) -> GPTClient:
    settings = SimpleNamespace(
        GPT_MODEL="gpt-test",
        GPT_FUNCTION_TOOLS=[{"type": "function"}],
        GPT_SYSTEM_PROMPT="fixed-system-prompt",
    )
    openai_client = MagicMock()
    openai_client.chat.completions.create = create
    with patch("functions.config.settings.get_settings", return_value=settings), patch(
        "functions.shared.repositories.clients.gpt_client.AsyncOpenAI",
        return_value=openai_client,
    ):
        client = GPTClient(api_key="test-key")
    retry_with = getattr(type(client)._parse_slot, "retry_with")
    client._parse_slot = MethodType(retry_with(wait=wait_none()), client)
    return client


@pytest.mark.asyncio
async def test_gpt_blank_source_skips_provider_and_classifies_ambiguous_empty():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    create = AsyncMock()
    client = _gpt_client(create)

    result = await client.parse_menu(
        RawMenuData("20260712", RestaurantType.DODAM, {"중식1": "  \n\t"})
    )

    create.assert_not_awaited()
    slot_result = result.slot_results["중식1"]
    assert slot_result.outcome is ProcessingOutcome.AMBIGUOUS_EMPTY
    assert slot_result.reason_code == "EMPTY_SOURCE"
    assert slot_result.retry_count == 0
    assert result.menus["중식1"] == []
    assert SOURCE_SECRET not in output.getvalue()


@pytest.mark.asyncio
async def test_gpt_semantic_empty_is_not_retried():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    create = AsyncMock(return_value=_gpt_response([]))
    client = _gpt_client(create)

    result = await client.parse_menu(
        RawMenuData("20260712", RestaurantType.DODAM, {"중식1": SOURCE_SECRET})
    )

    assert create.await_count == 1
    slot_result = result.slot_results["중식1"]
    assert slot_result.outcome is ProcessingOutcome.PARSER_FAILURE
    assert slot_result.reason_code == "PARSE_EMPTY"
    assert slot_result.retry_count == 0
    assert SOURCE_SECRET not in output.getvalue()


@pytest.mark.asyncio
async def test_gpt_retry_then_success_emits_one_zero_based_retry_event():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    create = AsyncMock(side_effect=[TimeoutError("SECRET_TOKEN"), _gpt_response(["밥"])])
    client = _gpt_client(create)

    result = await client.parse_menu(
        RawMenuData("20260712", RestaurantType.DODAM, {"중식1": SOURCE_SECRET})
    )

    assert create.await_count == 2
    assert result.menus == {"중식1": ["밥"]}
    assert result.slot_results["중식1"].retry_count == 1
    retries = [event for event in _events(output) if event["event.name"] == "client.retry"]
    assert [event["retry_count"] for event in retries] == [1]
    assert SOURCE_SECRET not in output.getvalue()
    assert "SECRET_TOKEN" not in output.getvalue()


@pytest.mark.asyncio
async def test_gpt_exhaustion_is_isolated_per_slot():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    create = AsyncMock(
        side_effect=[
            ValueError("SECRET_TOKEN"),
            ValueError("SECRET_TOKEN"),
            ValueError("SECRET_TOKEN"),
            _gpt_response(["국"]),
        ]
    )
    client = _gpt_client(create)

    result = await client.parse_menu(
        RawMenuData(
            "20260712",
            RestaurantType.DODAM,
            {"중식1": SOURCE_SECRET, "석식1": "safe source"},
        )
    )

    assert create.await_count == 4
    assert result.menus["석식1"] == ["국"]
    assert result.slot_results["중식1"].outcome is ProcessingOutcome.PARSER_FAILURE
    assert result.slot_results["중식1"].reason_code == "PARSE_ERROR"
    retries = [event for event in _events(output) if event["event.name"] == "client.retry"]
    assert [event["retry_count"] for event in retries] == [1, 2]
    failures = [
        event
        for event in _events(output)
        if event.get("outcome") == ProcessingOutcome.PARSER_FAILURE.value
        and event.get("reason_code") == "PARSE_ERROR"
    ]
    assert len(failures) == 1
    assert "SECRET_TOKEN" not in output.getvalue()


@pytest.mark.asyncio
async def test_spring_exhausted_emits_retries_and_one_safe_failure():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    client = SpringAPIClient("https://SECRET_TOKEN.invalid", environment="dev")
    retry_with = getattr(type(client).post_menu, "retry_with")
    client.post_menu = MethodType(retry_with(wait=wait_none()), client)
    response = MagicMock(status=503)
    response.raise_for_status.side_effect = RuntimeError("SECRET_TOKEN")

    with patch("aiohttp.ClientSession.post") as post:
        post.return_value.__aenter__.return_value = response
        with pytest.raises(MenuPostException):
            await client.post_menu(
                "20260712",
                RestaurantType.DODAM,
                TimeSlot.LUNCH,
                ["SECRET_TOKEN menu"],
                6000,
            )

    assert post.call_count == 3
    events = _events(output)
    retries = [event for event in events if event["event.name"] == "client.retry"]
    assert [event["retry_count"] for event in retries] == [1, 2]
    failures = [event for event in events if event.get("outcome") == "API_FAILURE"]
    assert len(failures) == 1
    assert failures[0]["stage"] == "menu_post"
    assert failures[0]["environment"] == "dev"
    assert failures[0]["status"] == 503
    assert failures[0]["menu_count"] == 1
    assert failures[0]["error.type"] == "MenuPostException"
    assert "duration_ms" in failures[0]
    assert "SECRET_TOKEN" not in output.getvalue()


@pytest.mark.asyncio
async def test_slack_exhausted_emits_retries_and_propagates_safe_failure():
    output = io.StringIO()
    initialize_observation_logger(stream=output)
    client = SlackClient("https://SECRET_TOKEN.invalid")
    retry_with = getattr(type(client)._send_message, "retry_with")
    client._send_message = MethodType(retry_with(wait=wait_none()), client)
    response = MagicMock(status=429)
    response.raise_for_status.side_effect = RuntimeError("SECRET_TOKEN")

    with patch("aiohttp.ClientSession.post") as post:
        post.return_value.__aenter__.return_value = response
        with pytest.raises(RuntimeError, match="Slack notification failed") as failure:
            await client._send_message("message SECRET_TOKEN")

    assert failure.value.__cause__ is None
    assert post.call_count == 3
    events = _events(output)
    retries = [event for event in events if event["event.name"] == "client.retry"]
    assert [event["retry_count"] for event in retries] == [1, 2]
    failures = [event for event in events if event.get("outcome") == "API_FAILURE"]
    assert len(failures) == 1
    assert failures[0]["stage"] == "slack_notify"
    assert failures[0]["status"] == 429
    assert failures[0]["message_length"] == len("message SECRET_TOKEN")
    assert failures[0]["error.type"] == "SlackNotificationError"
    assert "duration_ms" in failures[0]
    assert "SECRET_TOKEN" not in output.getvalue()
