import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """알림 서비스"""

    def __init__(self, container):
        self._container = container

    async def send_menu_notification(self, parsed_menu) -> bool:
        """메뉴 처리 완료 알림을 전송합니다."""
        logger.info(f"메뉴 알림 전송: {parsed_menu.restaurant.korean_name} {parsed_menu.date}")

        slack_client = self._container.get_slack_client()
        return await slack_client.send_menu_notification(parsed_menu)

    async def send_error_notification(self, error: Exception) -> bool:
        """에러 알림을 전송합니다."""
        logger.error(f"에러 알림 전송: {str(error)}")

        slack_client = self._container.get_slack_client()
        return await slack_client.send_error_notification(error)
