import asyncio
import json
import logging
from typing import Dict, List, Any

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.shared.models.model import RestaurantType

logger = logging.getLogger(__name__)


class SchedulingService:
    """스케줄링 서비스 - 주간 메뉴 처리 공통 로직"""

    def __init__(self, container):
        self._container = container

    async def process_weekly_schedule(self, restaurant_type: RestaurantType, weekdays: List[str]) -> Dict[str, Any]:
        """주간 스케줄 처리 공통 로직"""
        logger.info(f"{restaurant_type.korean_name} 주간 스케줄 처리 시작: {weekdays}")

        results = {}

        async with aiohttp.ClientSession() as session:
            # 1. 각 날짜별로 해당 식당 Lambda 호출
            tasks = [self._invoke_restaurant_lambda(session, restaurant_type, date) for date in weekdays]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for date, response_data in zip(weekdays, responses):
                if isinstance(response_data, Exception):
                    results[date] = {"error": str(response_data), "success": False}
                    logger.error(f"{restaurant_type.korean_name} {date} 처리 실패: {response_data}")
                else:
                    results[date] = response_data
                    logger.info(f"{restaurant_type.korean_name} {date} 처리 성공")

            # 2. Slack으로 결과 알림 전송
            notification_tasks = [
                self._send_slack_notification(session, restaurant_type, date, menu)
                for date, menu in results.items()
            ]
            await asyncio.gather(*notification_tasks, return_exceptions=True)

        logger.info(f"{restaurant_type.korean_name} 주간 스케줄 처리 완료")
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def _invoke_restaurant_lambda(self, session: aiohttp.ClientSession,
                                        restaurant_type: RestaurantType, date: str) -> Dict[str, Any]:
        """해당 식당의 Lambda를 호출합니다."""
        from functions.config.settings import get_settings
        settings = get_settings()

        # 식당별 Lambda URL 매핑
        lambda_url_map = {
            RestaurantType.HAKSIK: settings.HAKSIK_LAMBDA_BASE_URL,
            RestaurantType.DODAM: settings.DODAM_LAMBDA_BASE_URL,
            RestaurantType.DORMITORY: settings.DORMITORY_LAMBDA_BASE_URL,
            RestaurantType.FACULTY: settings.FACULTY_LAMBDA_BASE_URL,
        }

        lambda_url = lambda_url_map.get(restaurant_type)
        if not lambda_url:
            raise ValueError(f"Unknown restaurant type: {restaurant_type}")

        async with session.get(lambda_url, params={"date": date}) as response:
            response.raise_for_status()
            response_text = await response.text()
            response_data = json.loads(response_text)
            return response_data

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def _send_slack_notification(self, session: aiohttp.ClientSession,
                                       restaurant_type: RestaurantType, date: str, menu: Dict[str, Any]):
        """Slack으로 메뉴 알림을 전송합니다."""
        from functions.config.settings import get_settings
        settings = get_settings()

        payload = {
            "channel": "#api-notification",
            "username": "학식봇",
            "text": f"{restaurant_type.korean_name}({date})의 식단 {menu}",
            "icon_emoji": ":ghost:"
        }
        headers = {'Content-Type': 'application/json'}

        try:
            async with session.post(
                    settings.SLACK_WEBHOOK_URL,
                    data=json.dumps(payload),
                    headers=headers
            ) as response:
                await response.text()
                logger.debug(f"Slack 알림 전송 성공: {restaurant_type.korean_name} {date}")
        except Exception as e:
            logger.error(f"Slack 알림 전송 실패: {restaurant_type.korean_name} {date} - {e}")
