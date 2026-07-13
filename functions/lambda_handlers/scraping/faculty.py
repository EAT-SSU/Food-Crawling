from functions.lambda_handlers.handler_support import run_single_scraping_handler
from functions.shared.models.model import RestaurantType


def faculty_view(event, context):
    """교직원식당 메뉴 스크래핑 뷰"""
    return run_single_scraping_handler(
        event,
        context,
        RestaurantType.FACULTY,
        special_note="교직원식당은 점심만 운영됩니다",
    )


lambda_handler = faculty_view
