from functions.lambda_handlers.handler_support import run_general_schedule_handler
from functions.shared.models.model import RestaurantType
from functions.shared.utils.date_utils import WeekType


def dodam_schedule_view(event, context):
    """도담식당 주간 스케줄 뷰"""
    return run_general_schedule_handler(
        event,
        context,
        RestaurantType.DODAM,
        WeekType.INCLUDE_SATURDAY,
    )


lambda_handler = dodam_schedule_view
