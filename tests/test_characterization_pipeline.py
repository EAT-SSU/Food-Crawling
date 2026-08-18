import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from functions.shared.models.model import (
    MenuPricing,
    ParsedMenuData,
    ProcessingOutcome,
    RestaurantType,
    SlotProcessingResult,
)
from functions.shared.repositories.clients.gpt_client import GPTClient
from functions.shared.repositories.clients.slack_client import SlackClient
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient
from functions.shared.repositories.scrapers.dormitory_scraper import DormitoryScraper
from functions.shared.repositories.scrapers.source_classification import classify_general_source
from functions.shared.services.scraping_service import ScrapingService
from functions.shared.services.time_slot_strategy import TimeSlotStrategyFactory


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/characterization"
SOURCE = json.loads((FIXTURES / "source_contracts.json").read_text(encoding="utf-8"))
SPRING = json.loads((FIXTURES / "spring_responses.json").read_text(encoding="utf-8"))
GPT = json.loads((FIXTURES / "gpt_responses.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("restaurant_name", ["DODAM", "HAKSIK", "FACULTY"])
def test_soongguri_html_fixtures_freeze_source_text_shape(restaurant_name):
    restaurant = RestaurantType[restaurant_name]
    expected = SOURCE[restaurant_name]
    html = (FIXTURES / f"{restaurant_name.lower()}.html").read_text(encoding="utf-8")

    raw = classify_general_source(html, expected["date"], restaurant)

    assert raw.date == expected["date"]
    assert raw.restaurant is restaurant
    assert raw.menu_texts == expected["menu_texts"]
    assert {
        slot: result.outcome.value for slot, result in raw.slot_results.items()
    } == expected["slot_outcomes"]


def test_dormitory_html_fixture_freezes_weekly_source_text_shape():
    expected = SOURCE["DORMITORY"]
    html = (FIXTURES / "dormitory.html").read_text(encoding="utf-8")
    scraper = DormitoryScraper.__new__(DormitoryScraper)

    raw_menus = scraper._parse_html_to_raw_menu_data(html, 2026)

    assert [raw.date for raw in raw_menus] == expected["dates"]
    assert [raw.menu_texts for raw in raw_menus] == expected["menu_texts"]
    assert [
        {slot: result.outcome.value for slot, result in raw.slot_results.items()}
        for raw in raw_menus
    ] == expected["slot_outcomes"]


@pytest.mark.parametrize("restaurant_name", ["DODAM", "HAKSIK", "FACULTY", "DORMITORY"])
def test_restaurant_slot_time_and_price_mappings_are_frozen(restaurant_name):
    restaurant = RestaurantType[restaurant_name]
    strategy = TimeSlotStrategyFactory.get_strategy(restaurant)

    for source_slot, expected in SOURCE[restaurant_name]["publication"].items():
        time_slot = strategy.extract_time_slot(source_slot)
        if expected is None:
            assert time_slot is None
        else:
            assert time_slot is not None
            assert time_slot.english_name == expected["time"]
            assert MenuPricing.get_price(restaurant, time_slot) == expected["price"]


def _parsed_menu():
    return ParsedMenuData(
        date="20260713",
        restaurant=RestaurantType.DODAM,
        menus={"중식1": ["제육볶음", "쌀밥", "미역국"]},
        slot_results={
            "중식1": SlotProcessingResult(
                slot="중식1",
                stage="parse",
                outcome=ProcessingOutcome.SUCCESS,
                reason_code="PARSE_SUCCESS",
            )
        },
    )


@pytest.mark.asyncio
async def test_direct_and_scheduled_destination_fanout_is_frozen():
    dev = SimpleNamespace(environment="dev", post_menu=AsyncMock(return_value=True))
    prod = SimpleNamespace(environment="prod", post_menu=AsyncMock(return_value=True))
    service = ScrapingService(None, prod, dev, None)

    await service.send_to_api(_parsed_menu())
    dev.post_menu.assert_awaited_once()
    prod.post_menu.assert_not_awaited()

    dev.post_menu.reset_mock()
    await service.send_to_api(_parsed_menu(), is_dev=False)
    dev.post_menu.assert_awaited_once()
    prod.post_menu.assert_awaited_once()
    assert SOURCE["destinations"] == {
        "direct_scrape": ["dev"],
        "scheduled": ["dev", "prod"],
        "critical": {"direct_scrape": "dev", "scheduled": "prod"},
    }


@pytest.mark.asyncio
async def test_spring_post_path_query_body_and_timeout_match_fixture():
    request = SPRING["request"]
    response = MagicMock(status=200)
    response.raise_for_status.return_value = None

    with patch("aiohttp.ClientSession.post") as post:
        post.return_value.__aenter__.return_value = response
        result = await SpringAPIClient("https://spring.example/", "prod").post_menu(
            request["query"]["date"],
            RestaurantType[request["query"]["restaurant"]],
            next(
                slot
                for slot in MenuPricing.get_available_times(RestaurantType.DODAM)
                if slot.english_name == request["query"]["time"]
            ),
            request["body"]["menuNames"],
            request["body"]["price"],
        )

    assert result is True
    assert post.call_args.args == ("https://spring.example/meals/with-price",)
    assert post.call_args.kwargs["params"] == request["query"]
    assert post.call_args.kwargs["json"] == request["body"]
    assert post.call_args.kwargs["timeout"].total == request["timeout_seconds"]


def test_gpt_and_spring_response_fixtures_are_transport_shaped_and_frozen():
    assert len(GPT["valid_site_english"]["tool_calls"]) == 1
    assert json.loads(
        GPT["valid_site_english"]["tool_calls"][0]["arguments"]
    ) == {"all_menus": ["제육볶음", "쌀밥", "미역국"]}
    assert len(GPT["malformed"]["multiple_tool_calls"]["tool_calls"]) == 2
    assert SPRING["responses"]["accepted_empty"] == {"status": 204, "body": None}
    assert SPRING["responses"]["accepted_unmatched"]["body"]["unmatchedMainMenus"] == [
        {"nameKo": "없는메뉴", "nameEn": "Missing"}
    ]


def test_client_retry_attempts_and_fixed_waits_are_frozen():
    retry_functions = {
        "gpt": GPTClient._parse_slot,
        "spring": SpringAPIClient.post_menu,
        "slack": SlackClient._send_message,
    }

    for name, function in retry_functions.items():
        expected = SOURCE["retry_attempts"][name]
        retry = cast(Any, function).retry
        assert retry.stop.max_attempt_number == expected["attempts"]
        assert retry.wait.wait_fixed == expected["wait_seconds"]
