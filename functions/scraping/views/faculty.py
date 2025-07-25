import asyncio
import json
import logging

from functions.shared.models.exceptions import (
    HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName
)
from functions.shared.models.menu import RestaurantType, ParsedMenuData

logger = logging.getLogger(__name__)


def faculty_view(event, context):
    """교직원식당 메뉴 스크래핑 뷰 (Django view 함수 스타일)"""
    date = None

    try:
        # 1. 파라미터 추출 및 검증
        query_params = event.get("queryStringParameters") or {}
        date = query_params.get("date")

        if not date:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json; charset=utf-8'},
                'body': json.dumps({'error': 'date parameter is required'}, ensure_ascii=False)
            }

        logger.info(f"교직원식당 메뉴 요청: {date}")

        # 2. 비즈니스 로직 실행
        from functions.config.dependencies import get_container
        container = get_container()
        scraping_service = container.get_scraping_service()

        parsed_menu = asyncio.run(scraping_service.scrape_and_process(date, RestaurantType.FACULTY))

        # 3. 알림 전송
        notification_service = container.get_notification_service()
        asyncio.run(notification_service.send_menu_notification(parsed_menu))

        logger.info(f"교직원식당 메뉴 처리 완료: {date}")

        # 4. ParsedMenuData에서 직접 응답 생성 (교직원식당 특수 노트 포함)
        return parsed_menu.to_lambda_response(
            message=f"{RestaurantType.FACULTY.korean_name} 메뉴 처리 완료",
            special_note="교직원식당은 점심만 운영됩니다"
        )

    except (HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName) as e:
        logger.error(f"교직원식당 도메인 오류: {e}")

        # Slack 에러 알림
        try:
            from functions.config.dependencies import get_container
            container = get_container()
            notification_service = container.get_notification_service()
            asyncio.run(notification_service.send_error_notification(e))
        except Exception as error:
            logger.error(f"Slack 에러 알림 전송 실패: {error}")

        return ParsedMenuData.error_response(
            date=date or "unknown",
            restaurant=RestaurantType.FACULTY,
            error=e,
            status_code=400
        )

    except Exception as e:
        logger.error(f"교직원식당 시스템 오류: {e}", exc_info=True)

        return ParsedMenuData.error_response(
            date=date or "unknown",
            restaurant=RestaurantType.FACULTY,
            error=Exception("Internal server error"),
            status_code=500
        )


# AWS Lambda 핸들러
lambda_handler = faculty_view
