from functions.lambda_handlers.handler_support import run_single_scraping_handler
from functions.shared.models.model import RestaurantType


def haksik_view(event, context):
    """학생식당 메뉴 스크래핑 뷰"""
    return run_single_scraping_handler(
        event,
        context,
        RestaurantType.HAKSIK,
        special_note="석식 메뉴는 1000원 조식으로 처리됨",
    )


lambda_handler = haksik_view
