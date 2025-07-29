import logging

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.shared.models.model import ParsedMenuData, RestaurantType

logger = logging.getLogger(__name__)


class SlackClient:
    """Slack 알림 클라이언트"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        """메뉴 알림 전송"""
        message = self._build_menu_message(parsed_menu)
        return await self._send_message(message)

    async def send_error_notification(self, date:str,restaurant_type:RestaurantType,exception: Exception) -> bool:
        """에러 알림 전송"""
        message = f"⚠️ {restaurant_type.korean_name}({date}) 메뉴 에러{str(exception)}\n"

        return await self._send_message(message)

    def _build_menu_message(self, parsed_menu: ParsedMenuData) -> str:
        """의미있는 메뉴 메시지 생성"""
        restaurant = parsed_menu.restaurant.korean_name
        date = parsed_menu.date
        success_slots = parsed_menu.get_successful_slots()

        # 메인 메시지
        message = f"🍽️ {restaurant}({date}) 메뉴\n"

        # 처리 실패가 있다면 알림 오류 메시지만 추가
        if parsed_menu.error_slots:
            message += f"⚠️ 실패: {', '.join(parsed_menu.error_slots)}"
            return message.strip()

        # 각 식사 시간별 전체 메뉴 표시
        for slot,menu in success_slots.items():
            menu_text = ", ".join(menu)
            message += f"• {slot}: {menu_text}\n"

        return message.strip()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def _send_message(self, message: str) -> bool:
        """Slack 메시지 전송"""
        payload = {
            "username": "학식봇",
            "text": message,
            "icon_emoji": ":fork_and_knife:"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        self.webhook_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Slack 전송 실패: {e}")
            raise