import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASL_PATH = ROOT / "statemachine" / "dormitory-retry-workflow.asl.json"
TEMPLATE_PATH = ROOT / "template.yml"

EXPECTED_RETRIES = [
    {
        "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException",
        ],
        "IntervalSeconds": 2,
        "MaxAttempts": 3,
        "BackoffRate": 2.0,
    },
    {
        "ErrorEquals": ["RetryableEmptyMenuError", "RetryableApiSendError"],
        "IntervalSeconds": 7200,
        "MaxAttempts": 5,
        "BackoffRate": 1.0,
    },
]


def _workflow():
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


def test_dormitory_invoke_payload_has_correlation_without_changing_retry_policy():
    invoke = _workflow()["States"]["InvokeDormitory"]

    assert invoke["Retry"] == EXPECTED_RETRIES
    assert invoke["Parameters"]["Payload"] == {
        "trigger": "step_functions",
        "execution_id.$": "$$.Execution.Id",
        "retry_count.$": "$$.State.RetryCount",
        "delayed_schedule": False,
    }


def test_final_notifier_payload_is_allowlisted_and_never_forwards_cause_or_state():
    workflow = _workflow()
    notify = workflow["States"]["NotifyFinalFailure"]["Parameters"]

    assert notify["Payload"] == {
        "trigger": "step_functions",
        "execution_id.$": "$$.Execution.Id",
        "restaurant": "DORMITORY",
        "error_type.$": "$.error.Error",
    }
    assert "Payload.$" not in notify
    assert "Cause" not in ASL_PATH.read_text(encoding="utf-8")


def test_eventbridge_inputs_use_internal_shape_instead_of_api_gateway_shape():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert template.count('"trigger": "eventbridge"') == 3
    assert template.count('"delayed_schedule": false') == 3
    assert '"httpMethod"' not in template
    assert '"queryStringParameters"' not in template
