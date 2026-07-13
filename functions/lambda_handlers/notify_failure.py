import asyncio
import json

from functions.lambda_handlers.handler_support import (
    handler_observation,
    parse_handler_event,
    raise_sanitized_handler_failure,
)
from functions.shared.models.model import (
    DateProcessingSummary,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.observability import emit_event
from functions.shared.utils.date_utils import WeekType, get_current_weekdays


_RESTAURANTS = {item.english_name: item for item in RestaurantType}
_LAMBDA_ERRORS = {
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
}
_RETRY_OUTCOMES = {
    "RetryableEmptyMenuError": (
        ProcessingOutcome.AMBIGUOUS_EMPTY,
        "RETRY_EXHAUSTED_EMPTY",
        "source_fetch",
    ),
    "RetryableApiSendError": (
        ProcessingOutcome.API_FAILURE,
        "RETRY_EXHAUSTED_API",
        "menu_post",
    ),
}


def notify_failure_handler(event, context):
    payload = event if isinstance(event, dict) else {}
    restaurant_value = payload.get("restaurant")
    restaurant = (
        _RESTAURANTS.get(restaurant_value, RestaurantType.DORMITORY)
        if isinstance(restaurant_value, str)
        else RestaurantType.DORMITORY
    )
    request = parse_handler_event(payload)
    target_date = request.target_date or get_current_weekdays(WeekType.FULL_WEEK)[0]
    raw_error_type = payload.get("error_type")
    error_type = raw_error_type if isinstance(raw_error_type, str) else "UnknownError"
    normalized_error_type = (
        error_type
        if error_type in _RETRY_OUTCOMES or error_type in _LAMBDA_ERRORS
        else "UnknownError"
    )

    with handler_observation(event, context, restaurant, "final-notifier") as observed:
        mapped = _RETRY_OUTCOMES.get(normalized_error_type)
        if mapped:
            outcome, reason_code, stage = mapped
            result = SlotProcessingResult(
                slot="__date__",
                stage=stage,
                outcome=outcome,
                reason_code=reason_code,
                error_type=normalized_error_type,
            )
            summary = DateProcessingSummary(
                date=target_date,
                restaurant=restaurant,
                menus={},
                slot_results={result.slot: result},
                date_outcome=outcome,
                reason_code=reason_code,
            )
        else:
            summary = DateProcessingSummary(
                date=target_date,
                restaurant=restaurant,
                menus={},
                slot_results={},
                system_error=True,
            )

        from functions.config.dependencies import get_container

        notification_service = get_container().get_notification_service()
        asyncio.run(notification_service.send_date_summary(summary))
        emit_event(
            "INFO",
            "final_failure_notification_sent",
            "slack_notify",
            date=target_date,
            **{"error.type": normalized_error_type},
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "final failure notified",
                    "error_type": normalized_error_type,
                },
                ensure_ascii=False,
            ),
        }
    raise_sanitized_handler_failure(observed)


lambda_handler = notify_failure_handler
