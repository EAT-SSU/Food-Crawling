import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yml").read_text(encoding="utf-8")
ASL = json.loads(
    (ROOT / "statemachine/dormitory-retry-workflow.asl.json").read_text(
        encoding="utf-8"
    )
)
CONTRACT = json.loads(
    (
        ROOT / "tests/fixtures/characterization/infrastructure.json"
    ).read_text(encoding="utf-8")
)


def _resource_blocks():
    lines = TEMPLATE.splitlines()
    start = lines.index("Resources:") + 1
    blocks = {}
    current = None
    for line in lines[start:]:
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current = line.strip()[:-1]
            blocks[current] = [line]
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def test_authoritative_snapshot_has_exactly_nine_lambda_resources_and_handlers():
    blocks = _resource_blocks()
    functions = {
        name: block
        for name, block in blocks.items()
        if "Type: AWS::Serverless::Function" in block
    }

    assert CONTRACT["authoritative_sha"] == "59d021dc5ad8a5d4a7449f4e807760dff4184d0e"
    assert set(functions) == set(CONTRACT["functions"])
    assert len(functions) == CONTRACT["function_contract"]["count"] == 9
    for logical_id, handler in CONTRACT["functions"].items():
        assert f"Handler: {handler}" in functions[logical_id]
        assert "!Ref PythonRequirementsLayer" in functions[logical_id]


def test_manual_invocation_surface_has_zero_public_apis_or_function_urls():
    contract = CONTRACT["function_contract"]
    blocks = _resource_blocks()
    pathless_functions = {
        "DodamScrapingFunction",
        "HaksikScrapingFunction",
        "FacultyScrapingFunction",
        "DormitoryScrapingFunction",
        "DormitorySchedulingFunction",
        "NotifyFailureFunction",
    }

    assert contract["manual_invocation"] == "lambda:InvokeFunction"
    assert contract["public_api_event_count"] == 0
    assert contract["function_url_count"] == 0
    assert "Type: Api" not in TEMPLATE
    assert "AWS::Serverless::Api" not in TEMPLATE
    assert "AWS::ApiGateway" not in TEMPLATE
    assert "FunctionUrlConfig" not in TEMPLATE
    assert '"httpMethod"' not in TEMPLATE
    assert '"path"' not in TEMPLATE
    for logical_id in pathless_functions:
        assert "Events:" not in blocks[logical_id]


def test_lambda_global_configuration_and_function_policy_absence_are_frozen():
    blocks = _resource_blocks()
    contract = CONTRACT["function_contract"]

    assert f"Runtime: {contract['runtime']}" in TEMPLATE
    assert f"Architectures: [{contract['architecture']}]" in TEMPLATE
    assert f"Timeout: {contract['timeout']}" in TEMPLATE
    assert f"MemorySize: {contract['memory']}" in TEMPLATE
    function_policy_count = sum(
        "Policies:" in blocks[logical_id] for logical_id in CONTRACT["functions"]
    )
    assert function_policy_count == contract["function_policy_count"] == 0


def test_three_eventbridge_inputs_and_state_machine_schedule_are_exact():
    blocks = _resource_blocks()
    schedule = CONTRACT["general_schedule"]

    for logical_id in schedule["logical_resources"]:
        block = blocks[logical_id]
        assert f"Type: {schedule['event_type']}" in block
        assert f"Schedule: {schedule['expression']}" in block
        assert '"trigger": "eventbridge"' in block
        assert '"delayed_schedule": false' in block
    assert "Type: Schedule" not in blocks["DormitorySchedulingFunction"]
    assert (
        f"Schedule: {CONTRACT['dormitory_schedule']['expression']}"
        in blocks[CONTRACT["state_machine"]["logical_resource"]]
    )
    assert TEMPLATE.count("Type: Schedule") == 4


def test_dormitory_asl_payloads_substitutions_policies_and_retries_are_exact():
    state_machine = CONTRACT["state_machine"]
    invoke = ASL["States"]["InvokeDormitory"]
    notify = ASL["States"]["NotifyFinalFailure"]
    block = _resource_blocks()[state_machine["logical_resource"]]

    assert invoke["Parameters"]["Payload"] == state_machine["invoke_payload"]
    assert notify["Parameters"]["Payload"] == state_machine["failure_payload"]
    assert invoke["Retry"] == [state_machine["local_retry"], state_machine["domain_retry"]]
    assert invoke["Catch"] == [
        {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "NotifyFinalFailure",
        }
    ]
    for substitution, target in state_machine["substitutions"].items():
        assert f"{substitution}: !GetAtt {target}" in block
    for function_id in state_machine["policies"]:
        assert f"FunctionName: !Ref {function_id}" in block
    assert block.count("LambdaInvokePolicy:") == 2
