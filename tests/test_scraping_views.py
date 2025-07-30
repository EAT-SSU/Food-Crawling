import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from functions.scheduling.views.dodam import dodam_schedule_view
from functions.scheduling.views.haksik import haksik_schedule_view
from functions.scraping.views.dodam import dodam_view
from functions.scraping.views.dormitory import dormitory_view
from functions.scraping.views.faculty import faculty_view
from functions.scraping.views.haksik import haksik_view
from functions.shared.models.model import ParsedMenuData, RestaurantType


class TestScrapingViews:
    """스크래핑 View 함수들 통합 테스트"""

    @pytest.fixture
    def mock_event_with_date(self):
        """날짜가 포함된 Mock 이벤트"""
        return {
            "queryStringParameters": {
                "date": "20240325"
            }
        }

    @pytest.fixture
    def mock_event_without_date(self):
        """날짜가 없는 Mock 이벤트"""
        return {
            "queryStringParameters": {}
        }

    @pytest.fixture
    def mock_context(self):
        """Mock Lambda 컨텍스트"""
        return MagicMock()

    @pytest.fixture
    def mock_successful_parsed_menu(self):
        """성공적인 파싱 결과 Mock"""
        return ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥", "김치"]},
            error_slots={},
            success=True
        )

    def test_dodam_view_success(self, mock_event_with_date, mock_context, mock_successful_parsed_menu):
        """도담식당 view 성공 테스트"""
        with patch('functions.config.dependencies.get_container') as mock_get_container:
            # Mock 컨테이너와 서비스들
            mock_container = MagicMock()
            mock_scraping_service = AsyncMock()
            mock_notification_service = AsyncMock()

            mock_container.get_scraping_service.return_value = mock_scraping_service
            mock_container.get_notification_service.return_value = mock_notification_service
            mock_get_container.return_value = mock_container

            # Mock 비즈니스 로직 결과
            mock_scraping_service.scrape_and_process.return_value = mock_successful_parsed_menu
            mock_notification_service.send_menu_notification.return_value = True

            # View 함수 호출
            response = dodam_view(mock_event_with_date, mock_context)

            # 응답 검증
            assert response['statusCode'] == 200

            body = json.loads(response['body'])
            assert body['success'] is True
            assert body['date'] == "20240325"
            assert body['restaurant'] == "도담식당"
            assert "중식1" in body['menus']

    def test_dodam_view_missing_date(self, mock_event_without_date, mock_context):
        """도담식당 view 날짜 누락 테스트"""
        response = dodam_view(mock_event_without_date, mock_context)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['success'] is False
        assert "date parameter is required" in body['error']

    def test_haksik_view_success(self, mock_event_with_date, mock_context):
        """학생식당 view 성공 테스트"""

        mock_parsed_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.HAKSIK,
            menus={"중식1": ["꼬치어묵우동", "칠리탕수육"], "석식1": ["얼큰콩나물국"]},
            error_slots={},
            success=True
        )

        with patch('functions.config.dependencies.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_scraping_service = AsyncMock()
            mock_notification_service = AsyncMock()

            mock_container.get_scraping_service.return_value = mock_scraping_service
            mock_container.get_notification_service.return_value = mock_notification_service
            mock_get_container.return_value = mock_container

            mock_scraping_service.scrape_and_process.return_value = mock_parsed_menu
            mock_notification_service.send_menu_notification.return_value = True

            response = haksik_view(mock_event_with_date, mock_context)

            assert response['statusCode'] == 200
            body = json.loads(response['body'])
            assert body['success'] is True
            assert body['restaurant'] == "학생식당"
            assert "석식 메뉴는 1000원 조식으로 처리됨" in body['special_note']

    def test_faculty_view_success(self, mock_event_with_date, mock_context):
        """교직원식당 view 성공 테스트"""

        mock_parsed_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.FACULTY,
            menus={"중식1": ["함박스테이크", "파인애플볶음밥"]},
            error_slots={},
            success=True
        )

        with patch('functions.config.dependencies.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_scraping_service = AsyncMock()
            mock_notification_service = AsyncMock()

            mock_container.get_scraping_service.return_value = mock_scraping_service
            mock_container.get_notification_service.return_value = mock_notification_service
            mock_get_container.return_value = mock_container

            mock_scraping_service.scrape_and_process.return_value = mock_parsed_menu
            mock_notification_service.send_menu_notification.return_value = True

            response = faculty_view(mock_event_with_date, mock_context)

            assert response['statusCode'] == 200
            body = json.loads(response['body'])
            assert body['success'] is True
            assert body['restaurant'] == "교직원식당"
            assert "교직원식당은 점심만 운영됩니다" in body['special_note']

    def test_dormitory_view_success(self, mock_event_with_date, mock_context):
        """기숙사식당 view 성공 테스트"""

        mock_parsed_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DORMITORY,
            menus={"중식": ["어묵국", "쌀밥"], "석식": ["참치김치볶음밥", "우동장국"]},
            error_slots={},
            success=True
        )

        with patch('functions.config.dependencies.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_scraping_service = AsyncMock()
            mock_notification_service = AsyncMock()

            mock_container.get_scraping_service.return_value = mock_scraping_service
            mock_container.get_notification_service.return_value = mock_notification_service
            mock_get_container.return_value = mock_container

            mock_scraping_service.scrape_and_process.return_value = mock_parsed_menu
            mock_notification_service.send_menu_notification.return_value = True

            response = dormitory_view(mock_event_with_date, mock_context)

            assert response['statusCode'] == 200
            body = json.loads(response['body'])
            assert body['success'] is True
            assert body['restaurant'] == "기숙사식당"
            assert "주말에는 조식을 운영하지 않습니다" in body['special_note']

    def test_view_with_holiday_exception(self, mock_event_with_date, mock_context):
        """휴무일 예외 처리 테스트"""
        from functions.shared.models.exceptions import HolidayException

        with patch('functions.config.dependencies.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_scraping_service = AsyncMock()
            mock_notification_service = AsyncMock()

            mock_container.get_scraping_service.return_value = mock_scraping_service
            mock_container.get_notification_service.return_value = mock_notification_service
            mock_get_container.return_value = mock_container

            # 휴무일 예외 발생
            mock_scraping_service.scrape_and_process.side_effect = HolidayException(
                "20240325", "휴무일 데이터"
            )
            mock_notification_service.send_error_notification.return_value = True

            response = dodam_view(mock_event_with_date, mock_context)

            assert response['statusCode'] == 400
            body = json.loads(response['body'])
            assert body['success'] is False
            assert "HolidayException" in body['error_type']

    def test_view_with_system_error(self, mock_event_with_date, mock_context):
        """시스템 오류 처리 테스트"""
        with patch('functions.config.dependencies.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_scraping_service = AsyncMock()
            mock_notification_service = AsyncMock()

            mock_container.get_scraping_service.return_value = mock_scraping_service
            mock_container.get_notification_service.return_value = mock_notification_service
            mock_get_container.return_value = mock_container

            # 시스템 오류 발생
            mock_scraping_service.scrape_and_process.side_effect = Exception("시스템 오류")
            mock_notification_service.send_error_notification.return_value = True

            response = dodam_view(mock_event_with_date, mock_context)

            assert response['statusCode'] == 500
            body = json.loads(response['body'])
            assert body['success'] is False
            assert "Internal server error" in body['error']


class TestSchedulingViews:
    """스케줄링 View 함수들 통합 테스트"""

    @pytest.fixture
    def mock_context(self):
        """Mock Lambda 컨텍스트"""
        return MagicMock()

    @pytest.fixture
    def mock_event_normal(self):
        """일반 스케줄링 이벤트"""
        return {
            "queryStringParameters": {
                "delayed_schedule": "false"
            }
        }

    @pytest.fixture
    def mock_event_delayed(self):
        """지연 스케줄링 이벤트"""
        return {
            "queryStringParameters": {
                "delayed_schedule": "true"
            }
        }

    @pytest.fixture
    def mock_event_no_params(self):
        """파라미터 없는 이벤트"""
        return {}

    def test_dodam_schedule_view_success(self, mock_event_normal, mock_context):
        """도담식당 스케줄링 view 성공 테스트"""
        mock_results = {
            "20240325": {"success": True, "restaurant": "DODAM"},
            "20240326": {"success": True, "restaurant": "DODAM"}
        }

        with patch('functions.shared.utils.date_utils.get_next_weekdays') as mock_weekdays:
            mock_weekdays.return_value = ["20240325", "20240326"]

            with patch('functions.config.dependencies.get_container') as mock_get_container:
                mock_container = MagicMock()
                mock_scheduling_service = AsyncMock()

                mock_container.get_scheduling_service.return_value = mock_scheduling_service
                mock_get_container.return_value = mock_container

                mock_scheduling_service.process_weekly_schedule.return_value = mock_results

                response = dodam_schedule_view(mock_event_normal, mock_context)

                assert response['statusCode'] == 200
                body = json.loads(response['body'])
                assert "20240325" in body
                assert "20240326" in body

    def test_dodam_schedule_view_delayed(self, mock_event_delayed, mock_context):
        """도담식당 지연 스케줄링 테스트"""
        with patch('functions.shared.utils.date_utils.get_current_weekdays') as mock_current:
            mock_current.return_value = ["20240318", "20240319"]

            with patch('functions.config.dependencies.get_container') as mock_get_container:
                mock_container = MagicMock()
                mock_scheduling_service = AsyncMock()

                mock_container.get_scheduling_service.return_value = mock_scheduling_service
                mock_get_container.return_value = mock_container

                mock_scheduling_service.process_weekly_schedule.return_value = {}

                response = dodam_schedule_view(mock_event_delayed, mock_context)

                assert response['statusCode'] == 200
                # get_current_weekdays가 호출되어야 함
                mock_current.assert_called_once()

    def test_haksik_schedule_view_success(self, mock_event_normal, mock_context):
        """학생식당 스케줄링 view 성공 테스트"""
        mock_results = {
            "20240325": {"success": True, "restaurant": "HAKSIK"}
        }

        with patch('functions.shared.utils.date_utils.get_next_weekdays') as mock_weekdays:
            mock_weekdays.return_value = ["20240325"]

            with patch('functions.config.dependencies.get_container') as mock_get_container:
                mock_container = MagicMock()
                mock_scheduling_service = AsyncMock()

                mock_container.get_scheduling_service.return_value = mock_scheduling_service
                mock_get_container.return_value = mock_container

                mock_scheduling_service.process_weekly_schedule.return_value = mock_results

                response = haksik_schedule_view(mock_event_normal, mock_context)

                assert response['statusCode'] == 200
                body = json.loads(response['body'])
                assert "20240325" in body

    def test_schedule_view_error(self, mock_event_normal, mock_context):
        """스케줄링 view 오류 테스트"""
        with patch('functions.config.dependencies.get_container') as mock_get_container:
            mock_get_container.side_effect = Exception("컨테이너 오류")

            response = dodam_schedule_view(mock_event_normal, mock_context)

            assert response['statusCode'] == 500
            body = json.loads(response['body'])
            assert body['error'] == 'Internal server error'
            assert body['restaurant'] == 'DODAM'

    def test_schedule_view_no_params(self, mock_event_no_params, mock_context):
        """파라미터 없는 스케줄링 테스트"""
        with patch('functions.shared.utils.date_utils.get_next_weekdays') as mock_weekdays:
            mock_weekdays.return_value = ["20240325"]

            with patch('functions.config.dependencies.get_container') as mock_get_container:
                mock_container = MagicMock()
                mock_scheduling_service = AsyncMock()

                mock_container.get_scheduling_service.return_value = mock_scheduling_service
                mock_get_container.return_value = mock_container

                mock_scheduling_service.process_weekly_schedule.return_value = {}

                response = dodam_schedule_view(mock_event_no_params, mock_context)

                assert response['statusCode'] == 200
                # delayed_schedule가 없으면 get_next_weekdays가 호출되어야 함
                mock_weekdays.assert_called_once()
