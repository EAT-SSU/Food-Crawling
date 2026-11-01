import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yml").read_text(encoding="utf-8")

EXPECTED_SCHEDULES = {
    ("cron(0 8 ? * * *)", "DORMITORY", "current_week", False),
    ("cron(0 9 ? * * *)", "DORMITORY", "current_week", False),
    ("cron(0 10 ? * * *)", "DORMITORY", "current_week", True),
    *(
        schedule
        for restaurant in ("HAKSIK", "DODAM", "FACULTY")
        for schedule in (
            ("cron(0 16 ? * SUN *)", restaurant, "next_week", False),
            ("cron(0 20 ? * SUN *)", restaurant, "next_week", True),
            ("cron(5 16 ? * MON-THU *)", restaurant, "remaining_week", True),
        )
    ),
}


def _schedules():
    pattern = re.compile(
        r"Type: ScheduleV2\n\s+Properties:\n"
        r"\s+ScheduleExpression: (?P<cron>.+)\n"
        r"\s+ScheduleExpressionTimezone: (?P<tz>.+)\n"
        r"\s+Input: '(?P<input>.+)'"
    )
    return [match.groupdict() for match in pattern.finditer(TEMPLATE)]


def test_single_menu_function_with_runtime_only_code_uri():
    assert TEMPLATE.count("Type: AWS::Serverless::Function") == 1
    assert "\n  MenuFunction:\n" in TEMPLATE
    assert "CodeUri: src/" in TEMPLATE
    assert "Handler: functions.handler.lambda_handler" in TEMPLATE
    assert "ContentUri: layer/" in TEMPLATE
    assert sorted(path.name for path in (ROOT / "src").iterdir()) == ["functions"]
    assert sorted(path.name for path in (ROOT / "layer").iterdir()) == ["requirements.txt"]
    for forbidden in ("env.json", ".env", "samconfig.toml", "tests"):
        assert not list((ROOT / "src").rglob(forbidden))


def test_no_state_machines_alarms_or_reserved_concurrency():
    for forbidden in (
        "StateMachine",
        "AWS::CloudWatch::Alarm",
        "ReservedConcurrentExecutions",
        "OPERATION",
        "Type: Api",
        "FunctionUrlConfig",
    ):
        assert forbidden not in TEMPLATE
    assert not (ROOT / "statemachine").exists()


def test_schedules_are_kst_and_pass_restaurant_dates_final_and_both_environments():
    schedules = _schedules()

    assert len(schedules) == TEMPLATE.count("Type: ScheduleV2") == len(EXPECTED_SCHEDULES)
    assert {schedule["tz"] for schedule in schedules} == {"Asia/Seoul"}
    actual = set()
    for schedule in schedules:
        payload = json.loads(schedule["input"])
        assert payload["environments"] == ["dev", "prod"]
        actual.add((schedule["cron"], payload["restaurant"], payload["dates"], payload["final"]))
    assert actual == EXPECTED_SCHEDULES


def test_parameters_and_secret_handling():
    for name in ("GPTApiKey", "SlackWebhookUrl", "DormitoryRelayToken"):
        assert re.search(rf"  {name}:\n    Type: String\n    NoEcho: true", TEMPLATE)
    assert re.search(r'  DormitoryRelayUrl:\n    Type: String\n    Default: ""', TEMPLATE)
    for variable in (
        "GPT_API_KEY",
        "SLACK_WEBHOOK_URL",
        "API_BASE_URL",
        "DEV_API_BASE_URL",
        "DORMITORY_RELAY_URL",
        "DORMITORY_RELAY_TOKEN",
    ):
        assert f"{variable}: !Ref" in TEMPLATE


def test_one_retained_30_day_log_group():
    assert TEMPLATE.count("Type: AWS::Logs::LogGroup") == 1
    assert 'LogGroupName: !Sub "/aws/lambda/${MenuFunction}"' in TEMPLATE
    assert "RetentionInDays: 30" in TEMPLATE
    assert "DeletionPolicy: Retain" in TEMPLATE
