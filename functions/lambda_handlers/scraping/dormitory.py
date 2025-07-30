import asyncio
import logging

from functions.shared.models.exceptions import (
    HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantNameException
)
from functions.shared.models.model import RestaurantType, ResponseBuilder, ParsedMenuData

logger = logging.getLogger(__name__)


def dormitory_view(event, context):
    """기숙사식당 메뉴 스크래핑 뷰 (간결한 버전)"""
    date = None

    try:
        # 1. 파라미터 추출 및 검증
        query_params = event.get("queryStringParameters") or {}
        date = query_params.get("date")

        logger.info(f"기숙사식당 주간 메뉴 요청: {date}")

        # 2. 기숙사 전용 서비스 호출
        from functions.config.dependencies import get_container
        container = get_container()
        scraping_service = container.get_scraping_service()

        parsed_menus = asyncio.run(scraping_service.scrape_and_process_dormitory(date))

        # 3. 알림 전송
        notification_service = container.get_notification_service()
        for parsed_menu in parsed_menus:
            asyncio.run(notification_service.send_menu_notification(parsed_menu))

        logger.info(f"기숙사식당 주간 메뉴 처리 완료: {len(parsed_menus)}일치")

        # 4. 주간 결과를 하나의 ParsedMenuData로 직렬화
        combined_menus = {}
        combined_errors = {}

        for parsed_menu in parsed_menus:
            # 날짜별로 메뉴 구성: "20250310_중식" 형태
            for slot, items in parsed_menu.menus.items():
                combined_key = f"{parsed_menu.date}_{slot}"
                combined_menus[combined_key] = items

            # 에러도 날짜별로 구성
            for slot, error in parsed_menu.error_slots.items():
                combined_key = f"{parsed_menu.date}_{slot}"
                combined_errors[combined_key] = error

        # 통합된 ParsedMenuData 생성
        combined_parsed_menu = ParsedMenuData(
            date=f"{date}_weekly",  # 주간임을 표시
            restaurant=RestaurantType.DORMITORY,
            menus=combined_menus,
            error_slots=combined_errors,
            success=len(combined_errors) == 0
        )

        # 5. 기존 ResponseBuilder 그대로 사용
        return ResponseBuilder.create_success_response(
            combined_parsed_menu,
            message=f"{RestaurantType.DORMITORY.korean_name} 주간 메뉴 처리 완료 ({len(parsed_menus)}일치)",
            special_note="기숙사식당은 조식을 운영하지 않습니다"
        )

    except (HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantNameException) as e:
        logger.error(f"기숙사식당 도메인 오류: {e}")

        # Slack 에러 알림
        try:
            from functions.config.dependencies import get_container
            container = get_container()
            notification_service = container.get_notification_service()
            asyncio.run(notification_service.send_error_notification(e))
        except Exception as error:
            logger.error(f"Slack 에러 알림 전송 실패: {error}")

        return ResponseBuilder.create_error_response(
            date=date or "unknown",
            restaurant=RestaurantType.DORMITORY,
            error=e,
            status_code=400
        )

    except Exception as e:
        logger.error(f"기숙사식당 시스템 오류: {e}", exc_info=True)

        return ResponseBuilder.create_error_response(
            date=date or "unknown",
            restaurant=RestaurantType.DORMITORY,
            error=Exception("Internal server error"),
            status_code=500
        )


# AWS Lambda 핸들러
lambda_handler = dormitory_view