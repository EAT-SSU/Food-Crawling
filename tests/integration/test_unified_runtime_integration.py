import io
import json
import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from tenacity import wait_none

from functions import clients
from functions import handler


class _AsyncResponse:
    def __init__(self, *, status=200, text=""):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("source request failed")

    async def text(self):
        return self._text


class _ScraperSession:
    def __init__(self, html):
        self.html = html
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _AsyncResponse(text=self.html)


def _client_session(response_text="", status=200):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    response = _AsyncResponse(status=status, text=response_text)
    session.post.return_value = response
    return session


def _tool_response():
    arguments = {
        "menuNames": ["제육볶음"],
        "mainCandidates": [{"menuIndex": 0, "nameEn": "Spicy Pork"}],
    }
    call = SimpleNamespace(
        function=SimpleNamespace(
            name="extract_main_menus",
            arguments=json.dumps(arguments, ensure_ascii=False),
        )
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))]
    )


def test_unified_handler_integrates_real_wave2_modules_at_external_boundaries():
    html = (
        "<table><tr><td class='menu_nm'>중식1</td>"
        "<td>제육볶음 Spicy Pork</td></tr></table>"
    )
    scraper_session = _ScraperSession(html)
    spring_session = _client_session('{"unmatchedMainMenus": []}')
    slack_session = _client_session()
    openai_client = MagicMock()
    openai_client.chat.completions.create = AsyncMock(return_value=_tool_response())

    with (
        patch("functions.menu_ai.AsyncOpenAI", return_value=openai_client),
        patch(
            "functions.clients.aiohttp.ClientSession",
            side_effect=[scraper_session, spring_session, slack_session],
        ),
    ):
        response = handler.lambda_handler(
            {"operation": "scrape_dodam", "target_date": "20260713"},
            SimpleNamespace(aws_request_id="integration-request"),
        )

    assert response["statusCode"] == 200
    assert scraper_session.calls == [
        (("http://m.soongguri.com/m_req/m_menu.php?rcd=2&sdt=20260713",), {})
    ]
    openai_client.chat.completions.create.assert_awaited_once()
    assert spring_session.post.call_args.args == (
        "https://dev-api.example/meals/with-price",
    )
    assert spring_session.post.call_args.kwargs["json"] == {
        "price": 6000,
        "menuNames": ["제육볶음"],
        "mainMenus": [{"nameKo": "제육볶음", "nameEn": "Spicy Pork"}],
    }
    slack_text = slack_session.post.call_args.kwargs["json"]["text"]
    assert slack_text == (
        "🍽️ 도담식당 (20260713)\n"
        "• 중식1: 제육볶음\n"
        "  ↳ 대표: 제육볶음 (Spicy Pork)"
    )


def test_accepted_spring_is_not_replayed_when_slack_retries_exhaust(monkeypatch):
    secret = "SECRET_WEBHOOK_TOKEN"
    monkeypatch.setenv(
        "SLACK_WEBHOOK_URL", f"https://hooks.slack.test/{secret}"
    )
    html = (
        "<table><tr><td class='menu_nm'>중식1</td>"
        "<td>제육볶음 Spicy Pork</td></tr></table>"
    )
    scraper_session = _ScraperSession(html)
    spring_session = _client_session('{"unmatchedMainMenus": []}')
    slack_sessions = [_client_session("provider secret", status=500) for _ in range(3)]
    openai_client = MagicMock()
    openai_client.chat.completions.create = AsyncMock(return_value=_tool_response())
    fast_slack = cast(Any, clients.send_slack_text).retry_with(wait=wait_none())
    observation_stream = io.StringIO()
    observation_logger = logging.getLogger("food_crawling.observation")
    original_streams = []
    for log_handler in observation_logger.handlers:
        if isinstance(log_handler, logging.StreamHandler):
            original_streams.append((log_handler, log_handler.stream))
            log_handler.setStream(observation_stream)

    try:
        with (
            patch("functions.menu_ai.AsyncOpenAI", return_value=openai_client),
            patch("functions.clients.send_slack_text", fast_slack),
            patch(
                "functions.clients.aiohttp.ClientSession",
                side_effect=[scraper_session, spring_session, *slack_sessions],
            ),
        ):
            response = handler.lambda_handler(
                {"operation": "scrape_dodam", "target_date": "20260713"},
                SimpleNamespace(aws_request_id="slack-isolation-request"),
            )
    finally:
        for log_handler, original_stream in original_streams:
            log_handler.setStream(original_stream)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["success"] is True
    spring_session.post.assert_called_once()
    assert sum(session.post.call_count for session in slack_sessions) == 3
    observation = observation_stream.getvalue()
    assert '"event.name":"notification.failed"' in observation
    assert '"error_type":"SlackNotificationError"' in observation
    assert secret not in observation
    assert "provider secret" not in observation
