import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from functions.shared.models.model import RawMenuData, RestaurantType, TimeSlot, ParsedMenuData
from functions.shared.repositories.clients.gpt_client import GPTClient
from functions.shared.repositories.clients.slack_client import SlackClient
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient


class TestGPTClient:
    """GPT 클라이언트 테스트"""

    @pytest.fixture
    def gpt_client(self):
        """GPT 클라이언트 인스턴스"""
        return GPTClient(api_key="test-api-key")

    @pytest.fixture
    def sample_raw_menu(self):
        """샘플 원시 메뉴 데이터"""
        return RawMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menu_texts={
                "중식1": "도담 식당 매실우불고기 도라지오이생채 잡곡밥 우묵냉국",
                "석식1": "도담 식당 제육볶음 오징어청경채무침 쌀밥 된장국"
            }
        )

    @pytest.mark.asyncio
    async def test_parse_menu_success(self, gpt_client, sample_raw_menu):
        """GPT 메뉴 파싱 성공 테스트"""
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.function.arguments = json.dumps({
            "all_menus": ["매실우불고기", "도라지오이생채", "잡곡밥", "우묵냉국"]
        })
        mock_response.choices[0].message.tool_calls = [mock_tool_call]

        with patch.object(gpt_client.client.chat.completions, 'create', side_effect=mock_create):
            result = await gpt_client.parse_menu(sample_raw_menu)

            assert result.date == "20240325"
            assert len(result.error_slots) == 1  # 하나의 슬롯에서 오류 발생
            assert result.success is False


class TestSlackClient:
    """Slack 클라이언트 테스트"""

    @pytest.fixture
    def slack_client(self):
        """Slack 클라이언트 인스턴스"""
        return SlackClient(webhook_url="https://hooks.slack.com/test")

    @pytest.mark.asyncio
    async def test_send_notification_success(self, slack_client):
        """Slack 알림 전송 성공 테스트"""
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.raise_for_status.return_value = None
            mock_post.return_value.__aenter__.return_value = mock_response

            result = await slack_client.send_notification("테스트 메시지")

            assert result is True
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_menu_notification(self, slack_client):
        """메뉴 알림 전송 테스트"""

        parsed_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"]},
            error_slots={},
            success=True
        )

        with patch.object(slack_client, 'send_notification', return_value=True) as mock_send:
            result = await slack_client.send_menu_notification(parsed_menu)

            assert result is True
            mock_send.assert_called_once()
            # 메시지에 식당명과 날짜가 포함되어 있는지 확인
            call_args = mock_send.call_args[0][0]
            assert "도담식당" in call_args
            assert "20240325" in call_args

    @pytest.mark.asyncio
    async def test_send_error_notification(self, slack_client):
        """에러 알림 전송 테스트"""
        error = Exception("테스트 에러")

        with patch.object(slack_client, 'send_notification', return_value=True) as mock_send:
            result = await slack_client.send_error_notification(error)

            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0][0]
            assert "오류 발생" in call_args


class TestSpringAPIClient:
    """Spring API 클라이언트 테스트"""

    @pytest.fixture
    def api_client(self):
        """Spring API 클라이언트 인스턴스"""
        return SpringAPIClient(base_url="https://api.test.com")

    @pytest.mark.asyncio
    async def test_post_menu_success(self, api_client):
        """메뉴 API 전송 성공 테스트"""
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.raise_for_status.return_value = None
            mock_post.return_value.__aenter__.return_value = mock_response

            result = await api_client.post_menu(
                date="20240325",
                restaurant=RestaurantType.DODAM,
                time_slot=TimeSlot.LUNCH,
                menus=["김치찌개", "밥", "김치"],
                price=6000
            )

            assert result is True
            mock_post.assert_called_once()

            # 호출 인자 검증
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs['params']['date'] == "20240325"
            assert call_kwargs['params']['restaurant'] == RestaurantType.DODAM
            assert call_kwargs['params']['time'] == TimeSlot.LUNCH

    @pytest.mark.asyncio
    async def test_post_menu_failure(self, api_client):
        """메뉴 API 전송 실패 테스트"""
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.raise_for_status.side_effect = Exception("API 오류")
            mock_post.return_value.__aenter__.return_value = mock_response

            with pytest.raises(Exception):
                await api_client.post_menu(
                    date="20240325",
                    restaurant=RestaurantType.DODAM,
                    time_slot=TimeSlot.LUNCH,
                    menus=["김치찌개", "밥"],
                    price=6000
                )
