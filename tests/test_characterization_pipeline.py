import json
from pathlib import Path
from typing import Any, cast

import pytest

from functions import clients, handler, menu_ai, scraper


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/characterization"
SOURCE = json.loads((FIXTURES / "source_contracts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("restaurant", ["DODAM", "HAKSIK", "FACULTY"])
def test_soongguri_source_shapes_are_frozen(restaurant):
    expected = SOURCE[restaurant]
    html = (FIXTURES / f"{restaurant.lower()}.html").read_text(encoding="utf-8")
    records = scraper.parse_menu_html(html, restaurant, [expected["date"]])

    assert {record.source_slot: record.raw_text for record in records} == expected["menu_texts"]
    assert {record.source_slot: record.outcome for record in records} == expected["slot_outcomes"]


def test_dormitory_source_shape_is_frozen_without_row_slicing():
    expected = SOURCE["DORMITORY"]
    html = (FIXTURES / "dormitory.html").read_text(encoding="utf-8")
    records = scraper.parse_menu_html(html, "DORMITORY", expected["dates"])

    assert sorted({record.date for record in records}) == expected["dates"]
    assert all(record.date in expected["dates"] for record in records)


@pytest.mark.parametrize("restaurant", ["DODAM", "HAKSIK", "FACULTY", "DORMITORY"])
def test_restaurant_slot_time_and_price_mappings_are_frozen(restaurant):
    config = handler.load_operation_config(f"scrape_{restaurant.lower()}")
    assert config is not None
    for source_slot, expected in SOURCE[restaurant]["publication"].items():
        assert handler._slot_policy(config, source_slot) == (
            None if expected is None else (expected["time"], expected["price"])
        )


def test_client_retry_attempts_and_fixed_waits_are_frozen():
    retry_functions = {
        "gpt": menu_ai._request_completion,
        "spring": clients.publish_spring_meal,
        "slack": clients.send_slack_text,
    }
    for name, function in retry_functions.items():
        expected = SOURCE["retry_attempts"][name]
        policy = cast(Any, function).retry
        assert policy.stop.max_attempt_number == expected["attempts"]
        assert policy.wait.wait_fixed == expected["wait_seconds"]


def test_destination_policy_is_direct_dev_and_scheduled_dev_then_prod():
    assert SOURCE["destinations"] == {
        "direct_scrape": ["dev"],
        "scheduled": ["dev", "prod"],
        "critical": {"direct_scrape": "dev", "scheduled": "prod"},
    }
