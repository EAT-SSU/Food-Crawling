from functions.lambda_handlers.handler_support import run_dormitory_schedule_handler


def dormitory_schedule_view(event, context):
    """기숙사식당 주간 스케줄 뷰"""
    return run_dormitory_schedule_handler(event, context)


lambda_handler = dormitory_schedule_view
