import io
from types import MethodType
from unittest.mock import AsyncMock, patch

import pytest
from tenacity import wait_none

from functions.shared.models.model import (
    DateProcessingSummary,
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import initialize_observation_logger
from functions.shared.repositories.clients.slack_client import SlackClient

SENTINELS = [
    "Critical",
    "Traceback",
    "<html",
    "SECRET_TOKEN",
    "Cause",
    "https://hooks.slack.com/fake-webhook",
]

FAKE_WEBHOOK = "https://hooks.slack.com/fake-webhook"


def _make_slot_result(
    slot: str,
    outcome: ProcessingOutcome,
    reason_code: str,
    stage: str = "menu_post",
) -> SlotProcessingResult:
    return SlotProcessingResult(
        slot=slot,
        stage=stage,
        outcome=outcome,
        reason_code=reason_code,
    )


def _success_slot(slot: str) -> SlotProcessingResult:
    return _make_slot_result(slot, ProcessingOutcome.SUCCESS, "SUCCESS", stage="menu_post")


def _parser_failure_slot(slot: str) -> SlotProcessingResult:
    return _make_slot_result(slot, ProcessingOutcome.PARSER_FAILURE, "PARSE_ERROR", stage="gpt_parse")


def _api_failure_slot(slot: str) -> SlotProcessingResult:
    return _make_slot_result(slot, ProcessingOutcome.API_FAILURE, "POST_ERROR", stage="menu_post")


def _ambiguous_slot(slot: str) -> SlotProcessingResult:
    return _make_slot_result(slot, ProcessingOutcome.AMBIGUOUS_EMPTY, "SOURCE_EMPTY", stage="source_fetch")


def _expected_empty_slot(slot: str) -> SlotProcessingResult:
    return _make_slot_result(slot, ProcessingOutcome.EXPECTED_EMPTY, "HOLIDAY", stage="source_fetch")


@pytest.fixture
def slack_client():
    return SlackClient(FAKE_WEBHOOK)


@pytest.fixture
def mixed_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={
            "중식1": ["김치찌개", "밥"],
            "석식1": ["된장찌개", "밥"],
            "중식4": [],
        },
        slot_results={
            "중식1": _success_slot("중식1"),
            "석식1": _success_slot("석식1"),
            "중식4": _parser_failure_slot("중식4"),
        },
    )


@pytest.fixture
def holiday_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        slot_results={},
        date_outcome=ProcessingOutcome.EXPECTED_EMPTY,
        reason_code="HOLIDAY",
    )


@pytest.fixture
def ambiguous_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={"중식1": []},
        slot_results={"중식1": _ambiguous_slot("중식1")},
    )


@pytest.fixture
def api_failure_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={"중식1": ["김치찌개"]},
        slot_results={"중식1": _api_failure_slot("중식1")},
    )


@pytest.fixture
def system_error_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={},
        slot_results={},
        system_error=True,
    )


@pytest.fixture
def malicious_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={"중식1": []},
        slot_results={
            "중식1": SlotProcessingResult(
                slot="중식1",
                stage="gpt_parse",
                outcome=ProcessingOutcome.PARSER_FAILURE,
                reason_code="PARSE_ERROR",
                error_type="ValueError",
            ),
        },
    )


@pytest.fixture
def ordering_summary():
    return DateProcessingSummary(
        date="20260712",
        restaurant=RestaurantType.DODAM,
        menus={
            "석식2": ["국"],
            "중식": ["밥"],
            "조식1": ["죽"],
            "중식1": ["김치찌개"],
            "석식1": ["된장찌개"],
            "조식": ["토스트"],
        },
        slot_results={
            "석식2": _success_slot("석식2"),
            "중식": _success_slot("중식"),
            "조식1": _success_slot("조식1"),
            "중식1": _success_slot("중식1"),
            "석식1": _success_slot("석식1"),
            "조식": _success_slot("조식"),
        },
    )


class TestBuildDateSummaryMessage:

    def test_header_format(self, slack_client, mixed_summary):
        msg = slack_client.build_date_summary_message(mixed_summary)
        assert "🍽️ 도담식당(20260712)" in msg

    def test_mixed_success_shows_all_successful_menus(self, slack_client, mixed_summary):
        msg = slack_client.build_date_summary_message(mixed_summary)
        assert "✅ 중식1: 김치찌개, 밥" in msg
        assert "✅ 석식1: 된장찌개, 밥" in msg

    def test_mixed_success_shows_parser_failure_slot(self, slack_client, mixed_summary):
        msg = slack_client.build_date_summary_message(mixed_summary)
        assert "⚠️ 중식4: 메뉴 파싱 실패" in msg

    def test_mixed_success_all_in_one_message(self, slack_client, mixed_summary):
        msg = slack_client.build_date_summary_message(mixed_summary)
        assert "✅" in msg
        assert "⚠️" in msg

    def test_holiday_renders_info_line_only(self, slack_client, holiday_summary):
        msg = slack_client.build_date_summary_message(holiday_summary)
        assert "ℹ️ 휴무일" in msg
        assert "⚠️" not in msg
        assert "Critical" not in msg

    def test_ambiguous_empty_slot(self, slack_client, ambiguous_summary):
        msg = slack_client.build_date_summary_message(ambiguous_summary)
        assert "⚠️ 중식1: 메뉴 미게시 여부 확인 필요" in msg

    def test_api_failure_at_menu_post(self, slack_client, api_failure_summary):
        msg = slack_client.build_date_summary_message(api_failure_summary)
        assert "⚠️ 중식1: 메뉴 저장 실패" in msg

    def test_api_failure_at_source_fetch_renders_fetch_wording(self, slack_client):
        summary = DateProcessingSummary(
            date="20260712",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": []},
            slot_results={
                "중식1": SlotProcessingResult(
                    slot="중식1",
                    stage="source_fetch",
                    outcome=ProcessingOutcome.API_FAILURE,
                    reason_code="SOURCE_HTTP_ERROR",
                ),
            },
        )
        msg = slack_client.build_date_summary_message(summary)
        assert "⚠️ 중식1: 메뉴 원본 조회 실패" in msg
        assert "메뉴 저장 실패" not in msg

    def test_api_failure_at_unknown_stage_renders_safe_fallback(self, slack_client):
        summary = DateProcessingSummary(
            date="20260712",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": []},
            slot_results={
                "중식1": SlotProcessingResult(
                    slot="중식1",
                    stage="unknown_stage",
                    outcome=ProcessingOutcome.API_FAILURE,
                    reason_code="SOME_ERROR",
                ),
            },
        )
        msg = slack_client.build_date_summary_message(summary)
        assert "⚠️ 중식1: 외부 연동 실패" in msg
        assert "메뉴 저장 실패" not in msg
        assert "메뉴 원본 조회 실패" not in msg
        assert "unknown_stage" not in msg
        assert "SOME_ERROR" not in msg

    def test_system_error_shows_generic_message(self, slack_client, system_error_summary):
        msg = slack_client.build_date_summary_message(system_error_summary)
        assert "⚠️ 처리 중 시스템 오류" in msg

    def test_system_error_does_not_assign_business_outcome(self, slack_client, system_error_summary):
        msg = slack_client.build_date_summary_message(system_error_summary)
        assert "✅" not in msg
        assert "ℹ️" not in msg

    def test_malicious_data_no_sentinel_in_message(self, slack_client, malicious_summary):
        msg = slack_client.build_date_summary_message(malicious_summary)
        for sentinel in SENTINELS:
            assert sentinel not in msg, f"Sentinel '{sentinel}' found in message"

    def test_no_exception_string_in_message(self, slack_client):
        summary = DateProcessingSummary(
            date="20260712",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": []},
            slot_results={
                "중식1": SlotProcessingResult(
                    slot="중식1",
                    stage="gpt_parse",
                    outcome=ProcessingOutcome.PARSER_FAILURE,
                    reason_code="PARSE_ERROR",
                    error_type="ValueError",
                ),
            },
        )
        msg = slack_client.build_date_summary_message(summary)
        assert "ValueError" not in msg
        assert "Traceback" not in msg

    def test_natural_slot_order_조식_중식_석식(self, slack_client, ordering_summary):
        msg = slack_client.build_date_summary_message(ordering_summary)
        lines = [line for line in msg.splitlines() if line.startswith("✅")]
        slots_in_order = [line.split(":")[0].replace("✅ ", "").strip() for line in lines]
        family_order = ["조식", "중식", "석식"]
        prev_idx = -1
        for slot in slots_in_order:
            for i, fam in enumerate(family_order):
                if slot.startswith(fam):
                    assert i >= prev_idx, f"Family order violated: {slots_in_order}"
                    prev_idx = i
                    break

    def test_natural_slot_order_numeric_suffix_ascending(self, slack_client, ordering_summary):
        msg = slack_client.build_date_summary_message(ordering_summary)
        lines = [line for line in msg.splitlines() if line.startswith("✅")]
        slots_in_order = [line.split(":")[0].replace("✅ ", "").strip() for line in lines]

        joshik = [s for s in slots_in_order if s.startswith("조식")]
        assert joshik == ["조식1", "조식"], f"조식 order wrong: {joshik}"

        jungsik = [s for s in slots_in_order if s.startswith("중식")]
        assert jungsik == ["중식1", "중식"], f"중식 order wrong: {jungsik}"

        seoksik = [s for s in slots_in_order if s.startswith("석식")]
        assert seoksik == ["석식1", "석식2"], f"석식 order wrong: {seoksik}"

    def test_slot_order_independent_of_insertion_order(self, slack_client):
        slots_a = {"석식1": ["국"], "중식1": ["밥"], "조식1": ["죽"]}
        slots_b = {"조식1": ["죽"], "중식1": ["밥"], "석식1": ["국"]}
        results_a = {k: _success_slot(k) for k in slots_a}
        results_b = {k: _success_slot(k) for k in slots_b}

        summary_a = DateProcessingSummary(
            date="20260712",
            restaurant=RestaurantType.DODAM,
            menus=slots_a,
            slot_results=results_a,
        )
        summary_b = DateProcessingSummary(
            date="20260712",
            restaurant=RestaurantType.DODAM,
            menus=slots_b,
            slot_results=results_b,
        )
        client = SlackClient(FAKE_WEBHOOK)
        msg_a = client.build_date_summary_message(summary_a)
        msg_b = client.build_date_summary_message(summary_b)
        assert msg_a == msg_b


class TestSendDateSummary:

    @pytest.mark.asyncio
    async def test_exactly_one_send_per_date(self, slack_client, mixed_summary):
        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await slack_client.send_date_summary(mixed_summary)
        assert mock_send.call_count == 1
        assert result is True

    @pytest.mark.asyncio
    async def test_send_date_summary_holiday(self, slack_client, holiday_summary):
        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await slack_client.send_date_summary(holiday_summary)
        assert mock_send.call_count == 1
        sent_message = mock_send.call_args[0][0]
        assert "ℹ️ 휴무일" in sent_message
        assert "Critical" not in sent_message

    @pytest.mark.asyncio
    async def test_send_date_summary_system_error(self, slack_client, system_error_summary):
        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await slack_client.send_date_summary(system_error_summary)
        assert mock_send.call_count == 1
        sent_message = mock_send.call_args[0][0]
        assert "⚠️ 처리 중 시스템 오류" in sent_message

    @pytest.mark.asyncio
    async def test_send_date_summary_no_sentinel_in_payload(self, slack_client, malicious_summary):
        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await slack_client.send_date_summary(malicious_summary)
        sent_message = mock_send.call_args[0][0]
        for sentinel in SENTINELS:
            assert sentinel not in sent_message, f"Sentinel '{sentinel}' in payload"

    @pytest.mark.asyncio
    async def test_send_date_summary_mixed_payload_contains_success_and_failure(
        self, slack_client, mixed_summary
    ):
        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await slack_client.send_date_summary(mixed_summary)
        sent_message = mock_send.call_args[0][0]
        assert "✅ 중식1" in sent_message
        assert "✅ 석식1" in sent_message
        assert "⚠️ 중식4" in sent_message

    @pytest.mark.asyncio
    async def test_send_date_summary_does_not_use_webhook_url_in_message(
        self, slack_client, mixed_summary
    ):
        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await slack_client.send_date_summary(mixed_summary)
        sent_message = mock_send.call_args[0][0]
        assert FAKE_WEBHOOK not in sent_message


class TestLegacyCompatibility:

    @pytest.mark.asyncio
    async def test_legacy_menu_wrapper_uses_summary_and_keeps_success_with_failure(
        self, slack_client
    ):
        parsed = ParsedMenuData(
            date="20260712",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["밥"], "석식1": []},
            error_slots={"석식1": RuntimeError("SECRET_TOKEN")},
            slot_results={
                "중식1": _success_slot("중식1"),
                "석식1": _parser_failure_slot("석식1"),
            },
        )

        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as send:
            send.return_value = True
            await slack_client.send_menu_notification(parsed)

        assert send.await_args is not None
        message = send.await_args.args[0]
        assert "✅ 중식1: 밥" in message
        assert "⚠️ 석식1: 메뉴 파싱 실패" in message
        for sentinel in SENTINELS:
            assert sentinel not in message

    @pytest.mark.asyncio
    async def test_legacy_error_wrapper_ignores_malicious_exception(self, slack_client):
        malicious = RuntimeError("Critical SECRET_TOKEN Traceback Cause")

        with patch.object(slack_client, "_send_message", new_callable=AsyncMock) as send:
            send.return_value = True
            await slack_client.send_error_notification(
                malicious,
                date="20260712",
                restaurant_type=RestaurantType.DODAM,
            )

        assert send.await_args is not None
        message = send.await_args.args[0]
        assert message == "🍽️ 도담식당(20260712)\n⚠️ 처리 중 시스템 오류"
        for sentinel in SENTINELS:
            assert sentinel not in message

    @pytest.mark.asyncio
    async def test_notification_service_legacy_error_path_cannot_leak_exception(self):
        from functions.shared.services.notification_service import NotificationService

        client = SlackClient(FAKE_WEBHOOK)
        service = NotificationService(client)
        with patch.object(client, "_send_message", new_callable=AsyncMock) as send:
            send.return_value = True
            await service.send_error_notification(
                RuntimeError("Critical SECRET_TOKEN Traceback Cause"),
                date="20260712",
                restaurant_type=RestaurantType.FACULTY,
            )

        assert send.await_args is not None
        message = send.await_args.args[0]
        assert "처리 중 시스템 오류" in message
        for sentinel in SENTINELS:
            assert sentinel not in message


class TestNotificationServiceFacade:

    @pytest.mark.asyncio
    async def test_notification_service_has_send_date_summary(self, mixed_summary):
        from functions.shared.services.notification_service import NotificationService

        mock_slack = AsyncMock()
        mock_slack.send_date_summary = AsyncMock(return_value=True)
        service = NotificationService(mock_slack)

        result = await service.send_date_summary(mixed_summary)

        mock_slack.send_date_summary.assert_awaited_once_with(mixed_summary)
        assert result is True

    @pytest.mark.asyncio
    async def test_notification_service_send_date_summary_passes_summary_through(
        self, holiday_summary
    ):
        from functions.shared.services.notification_service import NotificationService

        mock_slack = AsyncMock()
        mock_slack.send_date_summary = AsyncMock(return_value=True)
        service = NotificationService(mock_slack)

        await service.send_date_summary(holiday_summary)

        call_arg = mock_slack.send_date_summary.call_args[0][0]
        assert call_arg is holiday_summary
