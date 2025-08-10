import asyncio
import json
import logging

from functions.shared.models.model import RestaurantType, ParsedMenuData

logger = logging.getLogger(__name__)


def faculty_schedule_view(event, context):
    """교직원식당 주간 스케줄 뷰"""
    try:
        # 1. 파라미터 추출
        query_params = event.get("queryStringParameters") or {}
        delayed_schedule = query_params.get("delayed_schedule", "").lower() == 'true'

        logger.info(f"교직원식당 주간 스케줄 시작 (delayed: {delayed_schedule})")

        # 2. 날짜 목록 결정
        from functions.shared.utils.date_utils import get_next_weekdays, get_current_weekdays
        weekdays = get_current_weekdays() if delayed_schedule else get_next_weekdays()

        # 3. 일반 식당용 스케줄링 서비스 사용
        from functions.config.dependencies import get_container
        container = get_container()
        scheduling_service = container.get_scheduling_service()

        results: ParsedMenuData = asyncio.run(scheduling_service.process_weekly_schedule_general(
            RestaurantType.FACULTY, weekdays, is_dev=False
        ))

        logger.info("교직원식당 주간 스케줄 완료")

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps(results.to_dict(), ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"교직원식당 스케줄링 오류: {e}", exc_info=True)

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps({
                'error': 'Internal server error',
                'restaurant': 'FACULTY'
            }, ensure_ascii=False)
        }


# AWS Lambda 핸들러
lambda_handler = faculty_schedule_view
