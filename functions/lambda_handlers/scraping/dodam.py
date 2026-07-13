from functions.lambda_handlers.handler_support import run_single_scraping_handler
from functions.shared.models.model import RestaurantType


def dodam_view(event, context):
    """도담식당 메뉴 스크래핑 뷰"""
    return run_single_scraping_handler(event, context, RestaurantType.DODAM)


lambda_handler = dodam_view
