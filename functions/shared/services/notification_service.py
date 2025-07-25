import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """알림 서비스 - 리팩토링된 버전"""

    def __init__(self, container):
        self._container = container

    async def send_menu_notification(self, parsed_menu) -> bool:
        """메뉴 처리 완료 알림을 전송합니다."""
        logger.info(f"메뉴 알림 전송: {parsed_menu.restaurant.korean_name} {parsed_menu.date}")

        slack_client = self._container.get_slack_client()

        # 간단한 메시지 생성
        message = self._create_simple_message(parsed_menu)
        return await slack_client.send_notification(message)

    async def send_error_notification(self, error: Exception) -> bool:
        """에러 알림을 전송합니다."""
        logger.error(f"에러 알림 전송: {str(error)}")

        slack_client = self._container.get_slack_client()
        return await slack_client.send_error_notification(error)

    def _create_simple_message(self, parsed_menu) -> str:
        """간단한 메시지 생성"""
        restaurant = parsed_menu.restaurant.korean_name
        date = parsed_menu.date

        # 성공한 슬롯과 전체 슬롯 개수 계산
        success_slots = parsed_menu.get_successful_slots()
        total_slots = parsed_menu.get_all_slots()

        success_count = len(success_slots)
        total_count = len(total_slots)

        if parsed_menu.error_slots:
            return f"{restaurant}({date}) - {success_count}/{total_count} 슬롯 성공 (부분 처리)"
        else:
            return f"{restaurant}({date}) - 전체 처리 완료 ({success_count} 슬롯)"
