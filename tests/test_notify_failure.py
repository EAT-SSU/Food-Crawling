import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from functions.lambda_handlers.notify_failure import notify_failure_handler
from functions.shared.models.model import ProcessingOutcome, RestaurantType
from functions.shared.observability import emit_event, initialize_observation_logger
from functions.shared.repositories.clients.slack_client import SlackClient


class _Context:
    aws_request_id = "notify-invocation"


def _container():
    notification = SimpleNamespace(send_date_summary=AsyncMock(return_value=True))
    return SimpleNamespace(
        get_notification_service=lambda: notification,
        notification=notification,
    )


@pytest.mark.parametrize(
    ("error_type", "outcome", "reason_code"),
    [
        (
            "RetryableEmptyMenuError",
            ProcessingOutcome.AMBIGUOUS_EMPTY,
            "RETRY_EXHAUSTED_EMPTY",
        ),
        (
            "RetryableApiSendError",
            ProcessingOutcome.API_FAILURE,
            "RETRY_EXHAUSTED_API",
        ),
    ],
)
def test_final_retry_failure_maps_to_one_safe_date_summary(
    error_type, outcome, reason_code
):
    container = _container()
    event = {
        "trigger": "step_functions",
        "execution_id": "execution-arn",
        "restaurant": "DORMITORY",
        "error_type": error_type,
        "target_date": "20260713",
    }

    with patch("functions.config.dependencies.get_container", return_value=container):
        response = notify_failure_handler(event, _Context())

    assert response["statusCode"] == 200
    summary = container.notification.send_date_summary.await_args.args[0]
    assert summary.date == "20260713"
    assert summary.restaurant is RestaurantType.DORMITORY
    assert summary.date_outcome is outcome
    assert summary.reason_code == reason_code
    assert next(iter(summary.slot_results.values())).reason_code == reason_code
    container.notification.send_date_summary.assert_awaited_once()


def test_final_notifier_never_reads_or_emits_raw_cause_and_resets_context():
    output = io.StringIO()
    initialize_observation_logger(output)
    container = _container()
    event = {
        "trigger": "step_functions",
        "execution_id": "execution-arn",
        "restaurant": "DORMITORY",
        "error_type": "Lambda.ServiceException",
        "Cause": "<html>SECRET_TOKEN provider body",
        "error": {"Cause": "SECRET_TOKEN nested"},
        "target_date": "20260713",
    }

    with patch("functions.config.dependencies.get_container", return_value=container):
        notify_failure_handler(event, _Context())
    emit_event("INFO", "after_notifier", "test")

    summary = container.notification.send_date_summary.await_args.args[0]
    assert summary.system_error is True
    assert summary.slot_results == {}
    message = SlackClient("https://hooks.slack.com/fake").build_date_summary_message(summary)
    assert "처리 중 시스템 오류" in message
    assert "SECRET_TOKEN" not in message
    assert "Cause" not in message
    assert "SECRET_TOKEN" not in output.getvalue()
    after = json.loads(output.getvalue().splitlines()[-1])
    assert after["run_id"] == "unknown"


def test_invalid_restaurant_and_date_fall_back_without_reflecting_raw_values():
    container = _container()
    event = {
        "restaurant": "<html>SECRET_TOKEN",
        "error_type": "Unknown.SECRET_TOKEN",
        "target_date": "SECRET_TOKEN",
    }

    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch(
            "functions.lambda_handlers.notify_failure.get_current_weekdays",
            return_value=["20260706"],
        ),
    ):
        response = notify_failure_handler(event, _Context())

    summary = container.notification.send_date_summary.await_args.args[0]
    assert summary.restaurant is RestaurantType.DORMITORY
    assert summary.date == "20260706"
    assert summary.system_error is True
    assert "SECRET_TOKEN" not in json.dumps(response)


def test_final_notification_observation_uses_semantic_error_type_field():
    container = _container()
    event = {
        "restaurant": "DORMITORY",
        "error_type": "RetryableEmptyMenuError",
        "target_date": "20260713",
    }

    with (
        patch("functions.config.dependencies.get_container", return_value=container),
        patch("functions.lambda_handlers.notify_failure.emit_event") as emit,
    ):
        notify_failure_handler(event, _Context())

    final_event = next(
        call
        for call in emit.call_args_list
        if call.args[1] == "final_failure_notification_sent"
    )
    assert final_event.kwargs["error.type"] == "RetryableEmptyMenuError"
    assert "error_type" not in final_event.kwargs
