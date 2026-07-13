import json
from pathlib import Path
from typing import cast


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "template.yml"
README_PATH = ROOT / "README.md"
DORMITORY_ASL_PATH = ROOT / "statemachine" / "dormitory-retry-workflow.asl.json"

FUNCTION_HANDLERS = {
    "DodamScrapingFunction": "functions.lambda_handlers.scraping.dodam.lambda_handler",
    "HaksikScrapingFunction": "functions.lambda_handlers.scraping.haksik.lambda_handler",
    "FacultyScrapingFunction": "functions.lambda_handlers.scraping.faculty.lambda_handler",
    "DormitoryScrapingFunction": "functions.lambda_handlers.scraping.dormitory.lambda_handler",
    "DodamSchedulingFunction": "functions.lambda_handlers.scheduling.dodam.lambda_handler",
    "HaksikSchedulingFunction": "functions.lambda_handlers.scheduling.haksik.lambda_handler",
    "FacultySchedulingFunction": "functions.lambda_handlers.scheduling.faculty.lambda_handler",
    "DormitorySchedulingFunction": "functions.lambda_handlers.scheduling.dormitory.lambda_handler",
    "NotifyFailureFunction": "functions.lambda_handlers.notify_failure.lambda_handler",
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
        "AWS::CloudWatch::Alarm",
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

    for function_id, handler in FUNCTION_HANDLERS.items():
        block = resources[function_id]
        assert f"Handler: {handler}" in block
        assert "!Ref PythonRequirementsLayer" in block


def test_preserves_three_direct_schedules_and_dormitory_state_machine_schedule():
    template = _template_text()
    resources = _resource_blocks(template)

    assert template.count("Type: Schedule") == 4
    for function_id in DIRECT_SCHEDULE_FUNCTIONS:
        block = resources[function_id]
        assert block.count("Type: Schedule") == 1
        assert "WeeklySchedule:" in block
        assert "Schedule: cron(0 7 ? * SUN *)" in block

    assert "Type: Schedule" not in resources["DormitorySchedulingFunction"]

    state_machine = resources["DormitoryRetryStateMachine"]
    assert "Type: AWS::Serverless::StateMachine" in state_machine
    assert "DefinitionUri: statemachine/dormitory-retry-workflow.asl.json" in state_machine
    assert "DormitorySchedulingFunctionArn: !GetAtt DormitorySchedulingFunction.Arn" in state_machine
    assert "NotifyFailureFunctionArn: !GetAtt NotifyFailureFunction.Arn" in state_machine
    assert state_machine.count("LambdaInvokePolicy:") == 2
    assert state_machine.count("Type: Schedule") == 1
    assert "Schedule: cron(0 23 ? * SUN *)" in state_machine
    assert "Logging:" not in state_machine
    assert "MenuRetryStateMachine" not in resources


def test_preserves_dormitory_retry_workflow():
    workflow = cast(
        dict[str, object],
        json.loads(DORMITORY_ASL_PATH.read_text(encoding="utf-8")),
    )
    states = cast(dict[str, object], workflow["States"])
    invoke = cast(dict[str, object], states["InvokeDormitory"])
    invoke_parameters = cast(dict[str, object], invoke["Parameters"])
    retries = cast(list[object], invoke["Retry"])
    notify = cast(dict[str, object], states["NotifyFinalFailure"])
    notify_parameters = cast(dict[str, object], notify["Parameters"])

    assert workflow["StartAt"] == "InvokeDormitory"
    assert set(states) == {"InvokeDormitory", "NotifyFinalFailure"}
    assert invoke_parameters["FunctionName"] == "${DormitorySchedulingFunctionArn}"
    assert retries[1] == {
        "ErrorEquals": ["RetryableEmptyMenuError", "RetryableApiSendError"],
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
