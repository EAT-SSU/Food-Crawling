from functions.lambda_handlers.handler_support import run_dormitory_scraping_handler


def dormitory_view(event, context):
    """기숙사식당 주간 메뉴 스크래핑 뷰"""
    return run_dormitory_scraping_handler(event, context)


lambda_handler = dormitory_view
