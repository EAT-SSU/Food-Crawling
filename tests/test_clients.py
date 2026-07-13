from types import MethodType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import wait_none

from functions.shared.models.exceptions import MenuPostException
from functions.shared.models.model import RestaurantType, TimeSlot
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient


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
            mock_response = MagicMock()
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

            call_url = mock_post.call_args[0][0]
            assert call_url == "https://api.test.com/meals/with-price"

            call_kwargs = mock_post.call_args[1]
            assert call_kwargs['params']['date'] == "20240325"
            assert call_kwargs['params']['restaurant'] == RestaurantType.DODAM.english_name
            assert call_kwargs['params']['time'] == TimeSlot.LUNCH.english_name

    @pytest.mark.asyncio
    async def test_post_menu_failure(self, api_client):
        """메뉴 API 전송 실패 테스트 - 재시도 소진 후 MenuPostException으로 정규화되어 전파"""
        retry_with = getattr(type(api_client).post_menu, "retry_with")
        api_client.post_menu = MethodType(retry_with(wait=wait_none()), api_client)
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock(side_effect=Exception("API 오류"))
            mock_post.return_value.__aenter__.return_value = mock_response

            with pytest.raises(MenuPostException):
                await api_client.post_menu(
                    date="20240325",
                    restaurant=RestaurantType.DODAM,
                    time_slot=TimeSlot.LUNCH,
                    menus=["김치찌개", "밥"],
                    price=6000
                )
