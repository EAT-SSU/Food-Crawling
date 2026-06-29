import asyncio
import json
import logging

logger = logging.getLogger(__name__)


def notify_failure_handler(event, context):
    logger.info(f"NotifyFailure 이벤트 수신: {json.dumps(event, ensure_ascii=False, default=str)}")

    error_info = event.get("error", {})
    error_type = error_info.get("Error", "UnknownError")
    error_cause = error_info.get("Cause", str(error_info))

    from functions.config.dependencies import get_container
    from functions.shared.models.model import RestaurantType
    notification_service = get_container().get_notification_service()

    final_error = Exception(
        f"[기숙사 최종 실패] 재시도 후에도 메뉴를 가져오지 못했습니다.\n"
        f"에러 타입: {error_type}\n"
        f"상세: {error_cause}"
    )

    asyncio.run(notification_service.send_error_notification(
        exception=final_error,
        restaurant_type=RestaurantType.DORMITORY
    ))

    logger.info("최종 실패 Slack 알림 전송 완료")

    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'final failure notified', 'error_type': error_type}, ensure_ascii=False)
    }


lambda_handler = notify_failure_handler
