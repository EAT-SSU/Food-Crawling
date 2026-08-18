from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

_DATE_PATTERN = re.compile(r"\d{8}")
_TRIGGERS = frozenset({"direct", "eventbridge", "iam", "local", "step_functions"})
_CONTENT_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


class RetryableEmptyMenuError(Exception):
    """Signal Step Functions that Dormitory menus are not published yet."""

    def __init__(self, target_date: str, restaurant: str = "DORMITORY") -> None:
        super().__init__("retryable empty menu")
        self.target_date = target_date
        self.restaurant = restaurant


class RetryableApiSendError(Exception):
    """Signal Step Functions that a Dormitory Spring publication failed."""

    def __init__(
        self,
        target_date: str,
        restaurant: str = "DORMITORY",
        failed_days: int = 0,
    ) -> None:
        super().__init__("retryable API send failure")
        self.target_date = target_date
        self.restaurant = restaurant
        self.failed_days = failed_days


_RESTAURANTS = MappingProxyType(
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

_OPERATION_SPECS = MappingProxyType(
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


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.lower() == "true"


def _date(value: object) -> str | None:
    return value if isinstance(value, str) and _DATE_PATTERN.fullmatch(value) else None


def _retry_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def parse_event(event: object) -> dict[str, Any]:
    payload = _mapping(event)
    query = _mapping(payload.get("queryStringParameters"))
    raw_trigger = payload.get("trigger")
    delayed = payload.get("delayed_schedule", query.get("delayed_schedule"))
    execution_id = payload.get("execution_id")
    return {
        "trigger": raw_trigger if raw_trigger in _TRIGGERS else "direct",
        "delayed_schedule": _boolean(delayed),
        "execution_id": execution_id
        if isinstance(execution_id, str) and execution_id
        else None,
        "retry_count": _retry_count(payload.get("retry_count", 0)),
        "target_date": _date(
            payload.get("target_date") or payload.get("date") or query.get("date")
        ),
    }


def resolve_operation(event: object) -> str | None:
    """Resolve the resource discriminator without importing configuration."""
    configured = os.getenv("OPERATION") or os.getenv("HANDLER_OPERATION")
    if configured:
        return configured
    candidate = _mapping(event).get("operation")
    return candidate if isinstance(candidate, str) and candidate else None


def load_operation_config(operation: str) -> Mapping[str, Any] | None:
    """Load Task 7 configuration lazily, with a dormant local policy fallback."""
    config_module = importlib.import_module("functions.config")
    external_loader = getattr(config_module, "load_operation_config", None)
    if callable(external_loader):
        loaded = external_loader(operation)
        return _mapping(loaded) or None

    spec = _OPERATION_SPECS.get(operation)
    if spec is None:
        return None
    kind, restaurant = spec
    return {
        "operation": operation,
        "kind": kind,
        "restaurant": restaurant,
        **_RESTAURANTS[restaurant],
    }


async def scrape(config: Mapping[str, Any], target_date: str) -> Sequence[Mapping[str, Any]]:
    """Lazy patch boundary for the Task 3 scraper module."""
    module = importlib.import_module("functions.scraper")
    result = await module.scrape(config["restaurant"], target_date)
    if isinstance(result, Mapping):
        return [result]
    return result


async def interpret_menu(
    config: Mapping[str, Any], raw_meal: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Lazy patch boundary for the Task 4 menu AI module."""
    module = importlib.import_module("functions.menu_ai")
    return await module.interpret_menu(raw_meal, config["restaurant"])


async def publish_menu(
    config: Mapping[str, Any], payload: Mapping[str, Any], environment: str
) -> Any:
    """Lazy patch boundary for accepted Spring writes in Task 5."""
    module = importlib.import_module("functions.clients")
    return await module.publish_menu(payload, environment=environment, config=config)


async def notify_slack(config: Mapping[str, Any], notification: Mapping[str, Any]) -> Any:
    """Lazy patch boundary; final failure reaches only this client function."""
    module = importlib.import_module("functions.clients")
    return await module.notify_slack(notification, config=config)


def _week_dates(day_count: int, *, next_week: bool) -> list[str]:
    now = datetime.now(ZoneInfo("Asia/Seoul")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday = now - timedelta(days=now.weekday())
    if next_week:
        monday += timedelta(days=7)
    return [(monday + timedelta(days=index)).strftime("%Y%m%d") for index in range(day_count)]


def _dates_for(config: Mapping[str, Any], request: Mapping[str, Any]) -> list[str]:
    target_date = request.get("target_date")
    if isinstance(target_date, str):
        return [target_date]
    if config["kind"] == "scrape":
        return _week_dates(7, next_week=False)[:1]
    if config["restaurant"] == "DORMITORY" or request["delayed_schedule"]:
        return _week_dates(int(config["week_days"]), next_week=False)
    return _week_dates(int(config["week_days"]), next_week=True)


def _slot_policy(config: Mapping[str, Any], source_slot: object) -> tuple[str, int] | None:
    if not isinstance(source_slot, str):
        return None
    for marker, policy in _mapping(config.get("slots")).items():
        if isinstance(marker, str) and marker in source_slot:
            time_slot, price = policy
            return str(time_slot), int(price)
    return None


def _result_value(result: Any, name: str, default: Any) -> Any:
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _meal_date(raw_meal: Mapping[str, Any], fallback: str) -> str:
    return _date(raw_meal.get("date")) or fallback


def _source_slot(raw_meal: Mapping[str, Any]) -> str:
    value = raw_meal.get("source_slot", raw_meal.get("slot", "unknown"))
    return value if isinstance(value, str) and value else "unknown"


def _menu_names(interpreted: Mapping[str, Any]) -> list[str]:
    value = interpreted.get("menuNames", interpreted.get("menu_names", []))
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _main_menus(interpreted: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = interpreted.get("mainMenus", interpreted.get("main_menus", []))
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


async def _process_source_date(
    config: Mapping[str, Any],
    target_date: str,
    *,
    scheduled: bool,
) -> list[dict[str, Any]]:
    raw_meals = list(await scrape(config, target_date))
    dormitory_retry = scheduled and config["restaurant"] == "DORMITORY"
    if dormitory_retry and not raw_meals:
        raise RetryableEmptyMenuError(target_date)

    summaries: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"menus": {}, "warnings": [], "errors": []}
    )
    critical_failures: set[str] = set()
    environments = ("dev", "prod") if scheduled else ("dev",)
    critical_environment = "prod" if scheduled else "dev"

    for raw_meal in raw_meals:
        meal_date = _meal_date(raw_meal, target_date)
        source_slot = _source_slot(raw_meal)
        summary = summaries[meal_date]
        try:
            interpreted = await interpret_menu(config, raw_meal)
        except (RetryableEmptyMenuError, RetryableApiSendError):
            raise
        except Exception as error:
            logger.warning("menu interpretation failed: %s", type(error).__name__)
            summary["errors"].append(
                {"slot": source_slot, "stage": "menu_ai", "error_type": type(error).__name__}
            )
            continue

        menu_names = _menu_names(interpreted)
        summary["menus"][source_slot] = menu_names
        policy = _slot_policy(config, source_slot)
        if policy is None:
            summary["warnings"].append(
                {"slot": source_slot, "reason": "unsupported source slot"}
            )
            continue
        time_slot, price = policy
        payload: dict[str, Any] = {
            "date": meal_date,
            "restaurant": config["restaurant"],
            "time": time_slot,
            "price": price,
            "menuNames": menu_names,
        }
        main_menus = _main_menus(interpreted)
        if main_menus:
            payload["mainMenus"] = main_menus

        for environment in environments:
            try:
                publication = await publish_menu(config, payload, environment)
            except (RetryableEmptyMenuError, RetryableApiSendError):
                raise
            except Exception as error:
                logger.warning("Spring publication failed: %s", type(error).__name__)
                summary["warnings"].append(
                    {
                        "slot": source_slot,
                        "environment": environment,
                        "reason": "publication failed",
                        "error_type": type(error).__name__,
                    }
                )
                if environment == critical_environment:
                    critical_failures.add(meal_date)
                continue

            unmatched = _result_value(publication, "unmatchedMainMenus", None)
            if unmatched is None:
                unmatched = _result_value(publication, "unmatched_main_menus", [])
            warnings = _result_value(publication, "warnings", [])
            if unmatched:
                summary["warnings"].append(
                    {"slot": source_slot, "reason": "unmatched main menus", "items": unmatched}
                )
            if warnings:
                summary["warnings"].append(
                    {"slot": source_slot, "reason": "accepted response warning", "items": warnings}
                )

    if dormitory_retry and critical_failures:
        raise RetryableApiSendError(target_date, failed_days=len(critical_failures))

    if not summaries:
        summaries[target_date]
    results: list[dict[str, Any]] = []
    for meal_date, summary in sorted(summaries.items()):
        notification = {
            "type": "date_summary",
            "date": meal_date,
            "restaurant": config["restaurant"],
            **summary,
        }
        await notify_slack(config, notification)
        results.append(
            {
                "date": meal_date,
                "restaurant": config["name_ko"],
                "menus": summary["menus"],
                "success": not summary["errors"] and meal_date not in critical_failures,
                "error_slots": {
                    item["slot"]: item["error_type"] for item in summary["errors"]
                },
                "warnings": summary["warnings"],
            }
        )
    return results


def _response(status_code: int, body: Mapping[str, Any] | Sequence[Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": dict(_CONTENT_HEADERS),
        "body": json.dumps(body, ensure_ascii=False),
    }


def _invalid_response(reason: str) -> dict[str, Any]:
    return _response(400, {"success": False, "error": reason})


async def _run_scrape(
    config: Mapping[str, Any], request: Mapping[str, Any], event: object
) -> dict[str, Any]:
    del event
    target_date = _dates_for(config, request)[0]
    results = await _process_source_date(config, target_date, scheduled=False)
    if config["restaurant"] == "DORMITORY":
        menus = {
            f"{result['date']}_{slot}": items
            for result in results
            for slot, items in result["menus"].items()
        }
        errors = {
            f"{result['date']}_{slot}": error
            for result in results
            for slot, error in result["error_slots"].items()
        }
        body = {
            "success": not errors,
            "date": f"{target_date}_weekly",
            "restaurant": config["name_ko"],
            "menus": menus,
            "parsing_errors": errors or None,
            "message": f"{config['name_ko']} 주간 메뉴 처리 완료 ({len(results)}일치)",
            "special_note": config.get("special_note"),
        }
    else:
        result = results[0]
        body = {
            "success": result["success"],
            "date": result["date"],
            "restaurant": config["name_ko"],
            "menus": result["menus"],
            "parsing_errors": result["error_slots"] or None,
            "message": f"{config['name_ko']} 메뉴 처리 완료",
            "special_note": config.get("special_note"),
        }
    return _response(200 if body["success"] else 400, body)


async def _run_schedule(
    config: Mapping[str, Any], request: Mapping[str, Any], event: object
) -> dict[str, Any]:
    del event
    dates = _dates_for(config, request)
    results: list[dict[str, Any]] = []
    if config["restaurant"] == "DORMITORY":
        results.extend(await _process_source_date(config, dates[0], scheduled=True))
    else:
        for target_date in dates:
            results.extend(await _process_source_date(config, target_date, scheduled=True))
    return _response(200, results)


async def _run_final_failure(
    config: Mapping[str, Any], request: Mapping[str, Any], event: object
) -> dict[str, Any]:
    payload = _mapping(event)
    raw_error_type = payload.get("error_type")
    known_errors = {
        "RetryableEmptyMenuError",
        "RetryableApiSendError",
        "Lambda.ServiceException",
        "Lambda.AWSLambdaException",
        "Lambda.SdkClientException",
        "Lambda.TooManyRequestsException",
    }
    error_type = raw_error_type if raw_error_type in known_errors else "UnknownError"
    target_date = request.get("target_date") or _week_dates(7, next_week=False)[0]
    await notify_slack(
        config,
        {
            "type": "final_failure",
            "date": target_date,
            "restaurant": config["restaurant"],
            "error_type": error_type,
            "retry_count": request["retry_count"],
        },
    )
    return _response(
        200,
        {"message": "final failure notified", "error_type": error_type},
    )


DISPATCH_TABLE: Mapping[
    str,
    Callable[
        [Mapping[str, Any], Mapping[str, Any], object],
        Awaitable[dict[str, Any]],
    ],
] = MappingProxyType(
    {
        "scrape_dodam": _run_scrape,
        "scrape_haksik": _run_scrape,
        "scrape_faculty": _run_scrape,
        "scrape_dormitory": _run_scrape,
        "schedule_dodam": _run_schedule,
        "schedule_haksik": _run_schedule,
        "schedule_faculty": _run_schedule,
        "schedule_dormitory": _run_schedule,
        "notify_final_failure": _run_final_failure,
    }
)


async def orchestrate(event: object, context: object) -> dict[str, Any]:
    """Resolve and execute exactly one operation inside one event-loop boundary."""
    del context
    operation = resolve_operation(event)
    if operation is None:
        return _invalid_response("missing operation")
    dispatcher = DISPATCH_TABLE.get(operation)
    if dispatcher is None:
        return _invalid_response("unknown operation")
    config = load_operation_config(operation)
    if config is None or config.get("operation", operation) != operation:
        return _invalid_response("operation configuration mismatch")
    request = parse_event(event)
    return await dispatcher(config, request, event)


def lambda_handler(event: object, context: object) -> dict[str, Any]:
    return asyncio.run(orchestrate(event, context))
