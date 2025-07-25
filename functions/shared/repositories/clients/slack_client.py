import json
import logging

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.shared.models.model import ParsedMenuData
from functions.shared.repositories.interfaces import NotificationClientInterface

logger = logging.getLogger(__name__)


class SlackClient(NotificationClientInterface):
    """Slack 알림 클라이언트"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def send_notification(self, message: str, channel: str = "#api-notification") -> bool:
        """Slack으로 알림을 전송합니다."""
        logger.info("Slack 알림 전송 시작")

        try:
            payload = {
                "channel": channel,
                "username": "학식봇",
                "text": message,
                "icon_emoji": ":ghost:"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                        self.webhook_url,
                        data=json.dumps(payload),
                        headers={'Content-Type': 'application/json'},
                        timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()

            logger.info("Slack 알림 전송 성공")
            return True

        except Exception as e:
            logger.error(f"Slack 알림 전송 실패: {e}")
            raise

    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        """메뉴 알림을 전송합니다."""
        message = f"{parsed_menu.restaurant.korean_name}({parsed_menu.date})의 식단 {parsed_menu.menus}"
        return await self.send_notification(message)

    async def send_error_notification(self, error: Exception) -> bool:
        """에러 알림을 전송합니다."""
        message = f"오류 발생: {str(error)}"
        return await self.send_notification(message)
