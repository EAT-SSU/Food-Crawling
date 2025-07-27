

import json
from unittest.mock import AsyncMock, patch

import pytest

from functions.shared.models.model import RestaurantType
from functions.shared.services.scheduling_service import SchedulingService


@pytest.fixture
def mock_container():
    """Mock DI 컨테이너"""
    # 이 테스트에서는 SchedulingService만 필요하므로 간단한 Mock 객체를 사용합니다.
    return AsyncMock()

@pytest.fixture
def scheduling_service(mock_container):
    """테스트용 SchedulingService 인스턴스"""
    return SchedulingService(mock_container)

@pytest.mark.asyncio
async def test_process_weekly_schedule_integration(scheduling_service):
    """
    SchedulingService 통합 테스트
    - 주간 스케줄 처리 시 외부 Lambda를 올바르게 호출하는지 검증합니다.
    - Lambda 호출은 aiohttp.ClientSession을 Mock하여 시뮬레이션합니다.
    """
    weekdays = ["20240325", "20240326", "20240327"]
    restaurant = RestaurantType.HAKSIK

    # aiohttp.ClientSession Mock 설정
    with patch('aiohttp.ClientSession') as mock_session_class:
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session

        # Mock Lambda 호출 응답 설정
        # 첫 번째 호출은 성공, 두 번째는 실패, 세 번째는 성공으로 가정
        mock_response_success1 = AsyncMock()
        mock_response_success1.status = 200
        mock_response_success1.text.return_value = json.dumps({
            "success": True, "date": "20240325", "restaurant": "HAKSIK"
        })
        mock_response_success1.raise_for_status.return_value = None

        mock_response_failure = AsyncMock()
        mock_response_failure.status = 500
        mock_response_failure.text.return_value = json.dumps({
            "success": False, "error": "Internal Server Error"
        })
        # 실패 시 raise_for_status()는 예외를 발생시킴
        mock_response_failure.raise_for_status.side_effect = Exception("Lambda Error")

        mock_response_success2 = AsyncMock()
        mock_response_success2.status = 200
        mock_response_success2.text.return_value = json.dumps({
            "success": True, "date": "20240327", "restaurant": "HAKSIK"
        })
        mock_response_success2.raise_for_status.return_value = None

        # session.get()이 호출될 때마다 다른 응답을 반환하도록 설정
        mock_session.get.return_value.__aenter__.side_effect = [
            mock_response_success1,
            mock_response_failure,
            mock_response_success2
        ]

        # Mock Slack 전송 (성공했다고 가정)
        mock_slack_response = AsyncMock()
        mock_slack_response.raise_for_status.return_value = None
        mock_session.post.return_value.__aenter__.return_value = mock_slack_response

        # get_settings Mock 설정
        with patch('functions.shared.services.scheduling_service.get_settings') as mock_settings:
            # 실제 URL 대신 테스트용 URL 설정
            mock_settings.return_value.HAKSIK_LAMBDA_BASE_URL = "https://test-lambda.com/haksik"
            mock_settings.return_value.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"

            # 서비스 실행
            results = await scheduling_service.process_weekly_schedule(restaurant, weekdays)

            # 검증
            # 1. Lambda 호출이 3번 발생했는지 확인
            assert mock_session.get.call_count == 3

            # 2. Slack 알림이 1번(실패 케이스) 발생했는지 확인
            assert mock_session.post.call_count == 1
            slack_call_body = json.loads(mock_session.post.call_args[1]['data'])
            assert "HAKSIK 스케줄링 실패" in slack_call_body['text']
            assert "20240326" in slack_call_body['text']

            # 3. 최종 결과 확인
            assert len(results) == 3
            assert results["20240325"]['success'] is True
            assert results["20240326"]['success'] is False
            assert results["20240327"]['success'] is True

