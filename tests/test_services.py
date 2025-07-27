from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from functions.shared.models.model import RestaurantType, ParsedMenuData, RawMenuData, TimeSlot
from functions.shared.services.notification_service import NotificationService
from functions.shared.services.scheduling_service import SchedulingService
from functions.shared.services.scraping_service import ScrapingService


class TestScrapingService:
    """스크래핑 서비스 테스트"""

    @pytest.fixture
    def mock_container(self):
        """Mock DI 컨테이너"""
        container = MagicMock()

        # Mock scraper
        mock_scraper = AsyncMock()
        container.get_scraper.return_value = mock_scraper

        # Mock parser
        mock_parser = AsyncMock()
        container.get_parser.return_value = mock_parser

        # Mock API clients
        mock_dev_client = AsyncMock()
        mock_prod_client = AsyncMock()
        container.get_dev_api_client.return_value = mock_dev_client
        container.get_prod_api_client.return_value = mock_prod_client

        return container

    @pytest.fixture
    def scraping_service(self, mock_container):
        """스크래핑 서비스 인스턴스"""
        return ScrapingService(mock_container)

    @pytest.mark.asyncio
    async def test_scrape_and_process_success(self, scraping_service, mock_container):
        """전체 스크래핑 프로세스 성공 테스트"""

        # Mock 응답들 설정
        raw_menu = RawMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menu_texts={"중식1": "김치찌개 밥"}
        )

        parsed_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"]},
            error_slots={},
            success=True
        )

        mock_container.get_scraper.return_value.scrape_menu.return_value = raw_menu
        mock_container.get_parser.return_value.parse_menu.return_value = parsed_menu
        mock_container.get_dev_api_client.return_value.post_menu.return_value = True
        mock_container.get_prod_api_client.return_value.post_menu.return_value = True

        # Mock MenuPricing
        with patch('functions.shared.services.scraping_service.MenuPricing') as mock_pricing:
            mock_pricing.get_price.return_value = 6000

            # Mock TimeSlotStrategyFactory
            with patch('functions.shared.services.scraping_service.TimeSlotStrategyFactory') as mock_factory:
                mock_strategy = MagicMock()
                mock_strategy.extract_time_slot.return_value = TimeSlot.LUNCH
                mock_factory.get_strategy.return_value = mock_strategy

                result = await scraping_service.scrape_and_process(
                    "20240325", RestaurantType.DODAM, is_dev=False
                )

                assert result.date == "20240325"
                assert result.success is True

                # API 호출 검증
                mock_container.get_dev_api_client.return_value.post_menu.assert_called()
                mock_container.get_prod_api_client.return_value.post_menu.assert_called()


class TestNotificationService:
    """알림 서비스 테스트"""

    @pytest.fixture
    def mock_container(self):
        """Mock DI 컨테이너"""
        container = MagicMock()
        mock_slack_client = AsyncMock()
        container.get_slack_client.return_value = mock_slack_client
        return container

    @pytest.fixture
    def notification_service(self, mock_container):
        """알림 서비스 인스턴스"""
        return NotificationService(mock_container)

    @pytest.mark.asyncio
    async def test_send_menu_notification(self, notification_service, mock_container):
        """메뉴 알림 전송 테스트"""
        parsed_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"]},
            error_slots={},
            success=True
        )

        mock_container.get_slack_client.return_value.send_notification.return_value = True

        result = await notification_service.send_menu_notification(parsed_menu)

        assert result is True
        mock_container.get_slack_client.return_value.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_error_notification(self, notification_service, mock_container):
        """에러 알림 전송 테스트"""
        error = Exception("테스트 에러")
        mock_container.get_slack_client.return_value.send_error_notification.return_value = True

        result = await notification_service.send_error_notification(error)

        assert result is True
        mock_container.get_slack_client.return_value.send_error_notification.assert_called_once_with(error)

    def test_create_simple_message(self, notification_service):
        """간단한 메시지 생성 테스트"""
        # 성공 케이스
        success_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"], "석식1": ["불고기", "밥"]},
            error_slots={},
            success=True
        )

        message = notification_service._create_simple_message(success_menu)
        assert "도담식당(20240325)" in message
        assert "전체 처리 완료" in message

        # 부분 실패 케이스
        partial_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"], "석식1": []},
            error_slots={"석식1": "파싱 실패"},
            success=False
        )

        message = notification_service._create_simple_message(partial_menu)
        assert "도담식당(20240325)" in message
        assert "부분 처리" in message


class TestSchedulingService:
    """스케줄링 서비스 테스트"""

    @pytest.fixture
    def mock_container(self):
        """Mock DI 컨테이너"""
        return MagicMock()

    @pytest.fixture
    def scheduling_service(self, mock_container):
        """스케줄링 서비스 인스턴스"""
        return SchedulingService(mock_container)

    @pytest.mark.asyncio
    async def test_process_weekly_schedule(self, scheduling_service):
        """주간 스케줄 처리 테스트"""
        weekdays = ["20240325", "20240326", "20240327"]

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session

            # Mock Lambda 호출 응답
            mock_response = AsyncMock()
            mock_response.text.return_value = '{"success": true, "date": "20240325"}'
            mock_response.raise_for_status.return_value = None
            mock_session.get.return_value.__aenter__.return_value = mock_response

            # Mock Slack 전송
            mock_slack_response = AsyncMock()
            mock_slack_response.text.return_value = "ok"
            mock_session.post.return_value.__aenter__.return_value = mock_slack_response

            with patch('functions.shared.services.scheduling_service.get_settings') as mock_settings:
                mock_settings.return_value.HAKSIK_LAMBDA_BASE_URL = "https://test-lambda.com"
                mock_settings.return_value.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"

                result = await scheduling_service.process_weekly_schedule(
                    RestaurantType.HAKSIK, weekdays
                )

                assert len(result) == 3
                for date in weekdays:
                    assert date in result

    @pytest.mark.asyncio
    async def test_invoke_restaurant_lambda(self, scheduling_service):
        """식당 Lambda 호출 테스트"""
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.text.return_value = '{"success": true, "restaurant": "HAKSIK"}'
            mock_response.raise_for_status.return_value = None
            mock_get.return_value.__aenter__.return_value = mock_response

            with patch('functions.shared.services.scheduling_service.get_settings') as mock_settings:
                mock_settings.return_value.HAKSIK_LAMBDA_BASE_URL = "https://test-lambda.com"

                # Create a mock session
                mock_session = AsyncMock()

                result = await scheduling_service._invoke_restaurant_lambda(
                    mock_session, RestaurantType.HAKSIK, "20240325"
                )

                assert result["success"] is True
                assert result["restaurant"] == "HAKSIK"
