import json
from pathlib import Path

import pytest

from functions import handler


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/characterization/invocations.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("entry", FIXTURE["operations"], ids=lambda item: item["operation"])
def test_invocation_fixture_maps_to_unified_operation_and_event_contract(entry):
    request = handler.parse_event(entry["event"])
    config = handler.load_operation_config(entry["operation"])

    assert config is not None
    assert config["kind"] == entry["kind"]
    assert config["restaurant"] == entry["restaurant"]
    assert request["trigger"] == entry["event"].get("trigger", "direct")
    assert request["delayed_schedule"] is entry["event"].get(
        "delayed_schedule", False
    )
    assert request["execution_id"] == entry["event"].get("execution_id")
    assert request["retry_count"] == entry["event"].get("retry_count", 0)
    assert request["target_date"] == entry.get("expected_date")


def test_invalid_invocation_shapes_are_deterministic():
    unknown, missing = FIXTURE["invalid"]
    unknown_response = handler.lambda_handler(
        {**unknown["event"], "operation": unknown["operation"]}, None
    )
    missing_response = handler.lambda_handler(missing["event"], None)

    assert json.loads(unknown_response["body"])["error"] == unknown["expected_error"]
    assert json.loads(missing_response["body"])["error"] == missing["expected_error"]


def test_null_query_map_and_malformed_date_have_safe_defaults():
    request = handler.parse_event(
        {"queryStringParameters": None, "target_date": "not-a-date"}
    )
    assert request == {
        "trigger": "direct",
        "delayed_schedule": False,
        "execution_id": None,
        "retry_count": 0,
        "target_date": None,
    }
