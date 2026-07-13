from typing import Optional

from functions.shared.models.model import DateProcessingSummary, ParsedMenuData, RestaurantType


class NotificationService:
    """알림 서비스"""

    def __init__(self, slack_client):
        self._slack_client = slack_client

    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        """메뉴 처리 완료 알림"""
        return await self._slack_client.send_menu_notification(parsed_menu)

    async def send_error_notification(self, exception: Exception,date:Optional[str]=None,restaurant_type:Optional[RestaurantType]=None) -> bool:
        return await self._slack_client.send_error_notification(exception,date=date,restaurant_type=restaurant_type)

    async def send_date_summary(self, summary: DateProcessingSummary) -> bool:
        return await self._slack_client.send_date_summary(summary)
