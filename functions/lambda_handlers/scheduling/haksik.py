from functions.lambda_handlers.handler_support import run_general_schedule_handler
from functions.shared.models.model import RestaurantType
from functions.shared.utils.date_utils import WeekType


def haksik_schedule_view(event, context):
    """학생식당 주간 스케줄 뷰"""
    return run_general_schedule_handler(
        event,
        context,
        RestaurantType.HAKSIK,
        WeekType.WEEKDAY,
    )


lambda_handler = haksik_schedule_view
