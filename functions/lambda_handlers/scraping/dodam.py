import asyncio
import logging

from functions.shared.models.exceptions import (
    HolidayException, MenuFetchException, MenuParseException
)
from functions.shared.models.model import RestaurantType, ParsedMenuData, ResponseBuilder

logger = logging.getLogger(__name__)


def dodam_view(event, context):
    """도담식당 메뉴 스크래핑 뷰 (Django view 함수 스타일)"""
    date = None

    try:
        # 1. 파라미터 추출 및 검증
        query_params = event.get("queryStringParameters") or {}
        date = query_params.get("date")

        logger.info(f"도담식당 메뉴 요청: {date}")

        # 2. 비즈니스 로직 실행
        from functions.config.dependencies import get_container
        container = get_container()
        scraping_service = container.get_scraping_service()

        parsed_menu:ParsedMenuData = asyncio.run(scraping_service.scrape_and_process(date, RestaurantType.DODAM))

        # 3. 알림 전송
        notification_service = container.get_notification_service()
        asyncio.run(notification_service.send_menu_notification(parsed_menu))

        logger.info(f"도담식당 메뉴 처리 완료: {date}")

        # 4. ResponseBuilder를 사용하여 응답 생성
        return ResponseBuilder.create_success_response(
            parsed_menu,
            message=f"{RestaurantType.DODAM.korean_name} 메뉴 처리 완료"
        )

    except (HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName) as e:
        logger.error(f"도담식당 도메인 오류: {e}")

        # Slack 에러 알림
        try:
            from functions.config.dependencies import get_container
            container = get_container()
            notification_service = container.get_notification_service()
            asyncio.run(notification_service.send_error_notification(e, date=date, restaurant_type=RestaurantType.DODAM))
        except Exception as slack_error:
            logger.error(f"Slack 에러 알림 전송 실패: {slack_error}")

        # ResponseBuilder로 에러 응답 생성
        return ResponseBuilder.create_error_response(
            date=date or "unknown",
            restaurant=RestaurantType.DODAM,
            error=e,
            status_code=400
        )

    except Exception as e:
        logger.error(f"도담식당 시스템 오류: {e}", exc_info=True)

        # Slack 에러 알림
        try:
            from functions.config.dependencies import get_container
            container = get_container()
            notification_service = container.get_notification_service()
            asyncio.run(notification_service.send_error_notification(e, date=date, restaurant_type=RestaurantType.DODAM))
        except Exception as error:
            logger.error(f"Slack 에러 알림 전송 실패: {error}")

        return ResponseBuilder.create_error_response(
            date=date or "unknown",
            restaurant=RestaurantType.DODAM,
            error=Exception("Internal server error"),
            status_code=500
        )


# AWS Lambda 핸들러
lambda_handler = dodam_view
