from __future__ import annotations

import os
from types import MappingProxyType
from typing import Any, Mapping


_RESTAURANTS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "DODAM": {
            "name_ko": "도담식당",
            "week_days": 6,
            "slots": {"중식": ("LUNCH", 6000), "석식": ("DINNER", 6000)},
        },
        "HAKSIK": {
            "name_ko": "학생식당",
            "week_days": 5,
            "slots": {"중식": ("LUNCH", 5000), "석식": ("MORNING", 1000)},
            "special_note": "석식 메뉴는 1000원 조식으로 처리됨",
        },
        "FACULTY": {
            "name_ko": "교직원식당",
            "week_days": 5,
            "slots": {"중식": ("LUNCH", 7000)},
            "special_note": "교직원식당은 점심만 운영됩니다",
        },
        "DORMITORY": {
            "name_ko": "기숙사식당",
            "week_days": 7,
            "slots": {"중식": ("LUNCH", 5500), "석식": ("DINNER", 5500)},
            "special_note": "기숙사식당은 조식을 운영하지 않습니다",
        },
    }
)

_OPERATIONS = MappingProxyType(
    {
        "scrape_dodam": ("scrape", "DODAM"),
        "scrape_haksik": ("scrape", "HAKSIK"),
        "scrape_faculty": ("scrape", "FACULTY"),
        "scrape_dormitory": ("scrape", "DORMITORY"),
        "schedule_dodam": ("schedule", "DODAM"),
        "schedule_haksik": ("schedule", "HAKSIK"),
        "schedule_faculty": ("schedule", "FACULTY"),
        "schedule_dormitory": ("schedule", "DORMITORY"),
        "notify_final_failure": ("final_failure", "DORMITORY"),
    }
)


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required configuration: {name}")
    return value


def load_operation_config(operation: str) -> Mapping[str, Any] | None:
    spec = _OPERATIONS.get(operation)
    if spec is None:
        return None

    kind, restaurant = spec
    config: dict[str, Any] = {
        "operation": operation,
        "kind": kind,
        "restaurant": restaurant,
        **_RESTAURANTS[restaurant],
        "slack_webhook_url": _required_environment("SLACK_WEBHOOK_URL"),
    }
    if kind != "final_failure":
        config["gpt_api_key"] = _required_environment("GPT_API_KEY")
        config["dev_api_base_url"] = _required_environment("DEV_API_BASE_URL")
    if kind == "schedule":
        config["api_base_url"] = _required_environment("API_BASE_URL")
    return MappingProxyType(config)
