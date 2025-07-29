import logging

from functions.shared.models.model import ParsedMenuData, RestaurantType

logger = logging.getLogger(__name__)


class NotificationService:
    """알림 서비스"""

    def __init__(self, slack_client):
        self._slack_client = slack_client

    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        """메뉴 처리 완료 알림"""
        return await self._slack_client.send_menu_notification(parsed_menu)

    async def send_error_notification(self, date:str,restaurant_type:RestaurantType,exception: Exception) -> bool:
        """에러 알림"""
        return await self._slack_client.send_error_notification(date,restaurant_type,exception)
