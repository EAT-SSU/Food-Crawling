import asyncio
import json
import logging
from typing import List

from functions.shared.models.model import ParsedMenuData

logger = logging.getLogger(__name__)


def dormitory_schedule_view(event, context):
    """기숙사식당 주간 스케줄 뷰"""
    try:
        # 1. 파라미터 추출
        delayed_schedule = False
        if event.get("queryStringParameters"):
            delayed_schedule = bool(event["queryStringParameters"].get("delayed_schedule"))

        logger.info(f"기숙사식당 주간 스케줄 시작 (delayed: {delayed_schedule})")

        # 2. 날짜 목록 결정
        from functions.shared.utils.date_utils import get_next_weekdays, get_current_weekdays
        weekdays = get_current_weekdays() if delayed_schedule else get_next_weekdays()

        # 3. 기숙사 전용 스케줄링 서비스 사용
        from functions.config.dependencies import get_container
        container = get_container()
        scheduling_service = container.get_scheduling_service()

        results: List[ParsedMenuData] = asyncio.run(
            scheduling_service.process_weekly_schedule_dormitory(weekdays, is_dev=False))
        return_results = [result.to_dict() for result in results]

        logger.info("기숙사식당 주간 스케줄 완료")

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps(return_results, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"기숙사식당 스케줄링 오류: {e}", exc_info=True)

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps({
                'error': 'Internal server error',
                'restaurant': 'DORMITORY'
            }, ensure_ascii=False)
        }


# AWS Lambda 핸들러
lambda_handler = dormitory_schedule_view
