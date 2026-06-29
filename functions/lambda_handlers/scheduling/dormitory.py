import asyncio
import json
import logging
from typing import List

from functions.shared.models.exceptions import RetryableEmptyMenuError
from functions.shared.models.model import ParsedMenuData, RestaurantType
from functions.shared.utils.date_utils import WeekType

logger = logging.getLogger(__name__)


def dormitory_schedule_view(event, context):
    """기숙사식당 주간 스케줄 뷰"""
    query_params = event.get("queryStringParameters") or {}
    delayed_schedule = query_params.get("delayed_schedule", "").lower() == 'true'

    logger.info(f"기숙사식당 주간 스케줄 시작 (delayed: {delayed_schedule})")

    from functions.shared.utils.date_utils import get_current_weekdays
    # 250921 이후, 기숙사는 주말도 추가되었음, 다만 로직 문제로 날짜 변경됬을 시  functions/shared/scrapers/dormitory_scraper.py scrape_menu()를 확인해서 함께 변경해야함... :(
    weekdays = get_current_weekdays(week_type=WeekType.FULL_WEEK)

    from functions.config.dependencies import get_container
    container = get_container()
    scheduling_service = container.get_scheduling_service()

    results: List[ParsedMenuData] = asyncio.run(
        scheduling_service.process_weekly_schedule_dormitory(weekdays, is_dev=False))

    # 결과가 비면(사이트 미게시) 예외를 던져 Step Functions가 몇 시간 뒤 재시도하도록 한다
    if not results:
        raise RetryableEmptyMenuError(target_date=weekdays[0], restaurant_type=RestaurantType.DORMITORY)

    logger.info("기숙사식당 주간 스케줄 완료")

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json; charset=utf-8'},
        'body': json.dumps([r.to_dict() for r in results], ensure_ascii=False)
    }


# AWS Lambda 핸들러
lambda_handler = dormitory_schedule_view
