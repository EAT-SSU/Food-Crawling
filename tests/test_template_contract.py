import json
from pathlib import Path
from typing import cast


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "template.yml"
README_PATH = ROOT / "README.md"
MENU_ASL_PATH = ROOT / "statemachine" / "menu-retry-workflow.asl.json"

FUNCTION_HANDLERS = {
    "DodamScrapingFunction": "functions.handler.lambda_handler",
    "HaksikScrapingFunction": "functions.handler.lambda_handler",
    "FacultyScrapingFunction": "functions.handler.lambda_handler",
    "DormitoryScrapingFunction": "functions.handler.lambda_handler",
    "DodamSchedulingFunction": "functions.handler.lambda_handler",
    "HaksikSchedulingFunction": "functions.handler.lambda_handler",
    "FacultySchedulingFunction": "functions.handler.lambda_handler",
    "DormitorySchedulingFunction": "functions.handler.lambda_handler",
    "NotifyFailureFunction": "functions.handler.lambda_handler",
}

FUNCTION_OPERATIONS = {
    "DodamScrapingFunction": "scrape_dodam",
    "HaksikScrapingFunction": "scrape_haksik",
    "FacultyScrapingFunction": "scrape_faculty",
    "DormitoryScrapingFunction": "scrape_dormitory",
    "DodamSchedulingFunction": "schedule_dodam",
    "HaksikSchedulingFunction": "schedule_haksik",
    "FacultySchedulingFunction": "schedule_faculty",
    "DormitorySchedulingFunction": "schedule_dormitory",
    "NotifyFailureFunction": "notify_final_failure",
}

DIRECT_SCHEDULE_FUNCTIONS = {
    "DodamSchedulingFunction",
    "HaksikSchedulingFunction",
    "FacultySchedulingFunction",
}


def _template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _resource_blocks(template: str) -> dict[str, str]:
    lines = template.splitlines()
    resources_start = lines.index("Resources:") + 1
    resources_end = next(
        (index for index in range(resources_start, len(lines)) if lines[index] == "Outputs:"),
        len(lines),
    )
    blocks: dict[str, list[str]] = {}
    current_id = None

    for line in lines[resources_start:resources_end]:
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current_id = line.strip()[:-1]
            blocks[current_id] = [line]
        elif current_id is not None:
            blocks[current_id].append(line)

    return {resource_id: "\n".join(block) for resource_id, block in blocks.items()}


def test_no_public_api_events_outputs_or_prohibited_resources():
    template = _template_text()

    assert "Type: Api" not in template
    assert "ServerlessRestApi" not in template
    assert "Outputs:" not in template

    prohibited = (
        "AWS::Serverless::Api",
        "AWS::ApiGateway",
        "FunctionUrlConfig",
        "AWS::ApiGateway::ApiKey",
        "AWS::ApiGateway::UsagePlan",
        "AWS::SQS::Queue",
        "AWS::SNS::Topic",
        "DeadLetterQueue",
        "DestinationConfig",
        "AWS::CloudWatch::Dashboard",
        "AWS::Logs::MetricFilter",
        "Tracing: Active",
        "ApplicationSignals",
        "OpenTelemetry",
        "ADOT",
        "X-Ray",
    )
    for value in prohibited:
        assert value not in template


def test_preserves_all_nine_functions_and_global_configuration():
    template = _template_text()
    resources = _resource_blocks(template)
    function_ids = {
        resource_id
        for resource_id, block in resources.items()
        if "Type: AWS::Serverless::Function" in block
    }

    assert function_ids == set(FUNCTION_HANDLERS)
    assert template.count("Type: AWS::Serverless::Function") == 9
    assert "Runtime: python3.11" in template
    assert "Architectures: [arm64]" in template
    assert "Timeout: 300" in template
    assert "MemorySize: 512" in template

    layer = resources["PythonRequirementsLayer"]
    assert "CompatibleArchitectures:\n        - arm64" in layer
    assert "BuildArchitecture: arm64" in layer

    for function_id, handler in FUNCTION_HANDLERS.items():
        block = resources[function_id]
        assert f"Handler: {handler}" in block
        assert f"OPERATION: {FUNCTION_OPERATIONS[function_id]}" in block
        assert "!Ref PythonRequirementsLayer" in block


def test_all_schedules_run_through_per_restaurant_state_machines():
    template = _template_text()
    resources = _resource_blocks(template)

    assert template.count("Type: Schedule") == 8
    for function_id in DIRECT_SCHEDULE_FUNCTIONS:
        assert "Type: Schedule" not in resources[function_id]

    assert "Type: Schedule" not in resources["DormitorySchedulingFunction"]

    for restaurant in ("Dodam", "Haksik", "Faculty", "Dormitory"):
        state_machine = resources[f"{restaurant}RetryStateMachine"]
        assert "Type: AWS::Serverless::StateMachine" in state_machine
        assert "DefinitionUri: statemachine/menu-retry-workflow.asl.json" in state_machine
        assert "NotifyFailureFunctionArn: !GetAtt NotifyFailureFunction.Arn" in state_machine
        assert state_machine.count("LambdaInvokePolicy:") == 2
        assert state_machine.count("Type: Schedule") == 2
        assert "RecoverySchedule:" in state_machine
        assert resources[f"{restaurant}RetryStateMachineAlarm"].count("AWS::CloudWatch::Alarm") == 1


def test_preserves_common_retry_workflow():
    workflow = cast(
        dict[str, object],
        json.loads(MENU_ASL_PATH.read_text(encoding="utf-8")),
    )
    states = cast(dict[str, object], workflow["States"])
    invoke = cast(dict[str, object], states["InvokeSchedule"])
    invoke_parameters = cast(dict[str, object], invoke["Parameters"])
    retries = cast(list[object], invoke["Retry"])
    notify = cast(dict[str, object], states["NotifyFinalFailure"])
    notify_parameters = cast(dict[str, object], notify["Parameters"])

    assert workflow["StartAt"] == "InvokeSchedule"
    assert set(states) == {"InvokeSchedule", "NotifyFinalFailure", "MarkExecutionFailed"}
    assert invoke_parameters["FunctionName"] == "${SchedulingFunctionArn}"
    assert retries[1] == {
        "ErrorEquals": ["RetryableEmptyMenuError", "RetryableApiSendError", "RetryableMenuInterpretationError"],
        "IntervalSeconds": 7200,
        "MaxAttempts": 5,
        "BackoffRate": 1.0,
    }
    assert invoke["Catch"] == [
        {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "NotifyFinalFailure",
        }
    ]
    assert (
        notify_parameters["FunctionName"] == "${NotifyFailureFunctionArn}"
    )


def test_each_lambda_has_a_retained_30_day_log_group():
    template = _template_text()
    resources = _resource_blocks(template)
    log_groups = {
        resource_id: block
        for resource_id, block in resources.items()
        if "Type: AWS::Logs::LogGroup" in block
    }

    assert len(log_groups) == 9
    assert template.count("RetentionInDays: 30") == 9

    for function_id in FUNCTION_HANDLERS:
        block = log_groups[f"{function_id}LogGroup"]
        assert f"DependsOn: {function_id}" in block
        assert f'LogGroupName: !Sub "/aws/lambda/${{{function_id}}}"' in block
        assert "RetentionInDays: 30" in block
        assert "DeletionPolicy: Retain" in block
        assert "UpdateReplacePolicy: Retain" in block


def test_retention_runbook_requires_iam_invoke_and_import_before_deploy():
    readme = README_PATH.read_text(encoding="utf-8")

    assert "aws lambda invoke" in readme
    assert "IAM" in readme
    assert "CloudFormation IMPORT" in readme
    assert "/aws/lambda/" in readme
    assert "30일" in readme
    assert "배포를 중단" in readme
    assert "execute-api" not in readme
    assert "sam local start-api" not in readme
