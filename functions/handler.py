from __future__ import annotations

import asyncio
import contextvars
import hashlib
import importlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

_observation_context: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "observation_context", default={}
)
_observation_logger = logging.getLogger("food_crawling.observation")
if not _observation_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _observation_logger.addHandler(_handler)
_observation_logger.setLevel(logging.INFO)
_observation_logger.propagate = False

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
    """Load the authoritative flat Task 7 configuration lazily."""
    config_module = importlib.import_module("functions.config")
    loaded = config_module.load_operation_config(operation)
    return _mapping(loaded) or None


async def scrape(
    config: Mapping[str, Any],
    target_date: str,
    requested_dates: Sequence[str] | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Call the scraper's frozen record boundary and adapt its attributes."""
    module = importlib.import_module("functions.scraper")
    records = await module.fetch_meals(
        config["restaurant"], target_date, requested_dates=requested_dates
    )
    return [
        {
            "date": record.date,
            "restaurant": record.restaurant,
            "source_slot": record.source_slot,
            "raw_text": record.raw_text,
            "source_english": record.source_english,
            "outcome": record.outcome,
            "reason_code": record.reason_code,
        }
        for record in records
    ]


async def interpret_menu(
    config: Mapping[str, Any], raw_meal: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Lazy patch boundary for the Task 4 menu AI module."""
    module = importlib.import_module("functions.menu_ai")
    return await module.interpret_menu(
        config["gpt_api_key"],
        config["restaurant"],
        raw_meal.get("raw_text", ""),
        raw_meal.get("source_english", ()),
    )


async def publish_menu(
    config: Mapping[str, Any], payload: Mapping[str, Any], environment: str
) -> Any:
    """Lazy patch boundary for accepted Spring writes in Task 5."""
    module = importlib.import_module("functions.clients")
    base_url_key = "api_base_url" if environment == "prod" else "dev_api_base_url"
    return await module.publish_spring_meal(
        base_url=config[base_url_key],
        environment=environment,
        date=payload["date"],
        restaurant=payload["restaurant"],
        time=payload["time"],
        menu_names=payload["menuNames"],
        price=payload["price"],
        main_menus=payload.get("mainMenus"),
    )


async def notify_slack(config: Mapping[str, Any], notification: Mapping[str, Any]) -> Any:
    """Lazy patch boundary; final failure reaches only this client function."""
    module = importlib.import_module("functions.clients")
    text = module.format_slack_text(notification)
    return await module.send_slack_text(
        webhook_url=config["slack_webhook_url"], text=text
    )


def fingerprint_source(text: str) -> tuple[int, str]:
    encoded = text.encode("utf-8")
    return len(encoded), hashlib.sha256(encoded).hexdigest()[:12]


def emit_event(level: str, event_name: str, stage: str, **fields: Any) -> None:
    event = {
        **_observation_context.get(),
        "event.name": event_name,
        "stage": stage,
        "log.level": level.upper(),
        **{key: value for key, value in fields.items() if value is not None},
    }
    _observation_logger.log(
        getattr(logging, level.upper(), logging.INFO),
        json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str),
    )


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
    requested_dates: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    dormitory_retry = scheduled and config["restaurant"] == "DORMITORY"
    try:
        if requested_dates is None:
            raw_meals = list(await scrape(config, target_date))
        else:
            raw_meals = list(
                await scrape(config, target_date, requested_dates=requested_dates)
            )
    except Exception as error:
        outcome = getattr(error, "outcome", None)
        reason_code = getattr(error, "reason_code", "SOURCE_ERROR")
        if dormitory_retry and outcome == "AMBIGUOUS_EMPTY":
            raise RetryableEmptyMenuError(target_date) from None
        if outcome not in {"EXPECTED_EMPTY", "AMBIGUOUS_EMPTY"}:
            raise
        raw_meals = [
            {
                "date": getattr(error, "date", target_date),
                "source_slot": "전체",
                "raw_text": "",
                "source_english": (),
                "outcome": outcome,
                "reason_code": reason_code,
            }
        ]
    if dormitory_retry and requested_dates is not None:
        represented_dates = {
            meal_date
            for raw_meal in raw_meals
            if (meal_date := _date(raw_meal.get("date"))) is not None
        }
        if set(requested_dates) - represented_dates:
            raise RetryableEmptyMenuError(target_date)

    summaries: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"menus": {}, "warnings": [], "errors": [], "empty_reasons": {}}
    )
    critical_failures: set[str] = set()
    environments = ("dev", "prod") if scheduled else ("dev",)
    critical_environment = "prod" if scheduled else "dev"

    for raw_meal in raw_meals:
        meal_date = _meal_date(raw_meal, target_date)
        source_slot = _source_slot(raw_meal)
        summary = summaries[meal_date]
        raw_text = raw_meal.get("raw_text", "")
        if isinstance(raw_text, str):
            source_length, source_sha256 = fingerprint_source(raw_text)
            emit_event(
                "INFO",
                "source.classified",
                "classify",
                date=meal_date,
                slot=source_slot,
                outcome=raw_meal.get("outcome", "SUCCESS"),
                reason_code=raw_meal.get("reason_code"),
                source_length=source_length,
                source_sha256=source_sha256,
            )
        outcome = raw_meal.get("outcome", "SUCCESS")
        if outcome in {"EXPECTED_EMPTY", "AMBIGUOUS_EMPTY"}:
            reason_code = raw_meal.get("reason_code", "SOURCE_EMPTY")
            if dormitory_retry and outcome == "AMBIGUOUS_EMPTY":
                raise RetryableEmptyMenuError(meal_date)
            summary["menus"][source_slot] = []
            summary["empty_reasons"][source_slot] = reason_code
            if outcome == "AMBIGUOUS_EMPTY":
                summary["errors"].append(
                    {"slot": source_slot, "stage": "source", "error_type": str(reason_code)}
                )
            continue
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
                        "stage": "publication",
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
                    {
                        "slot": source_slot,
                        "stage": "unmatched",
                        "reason": "unmatched main menus",
                        "items": unmatched,
                    }
                )
            if warnings:
                summary["warnings"].append(
                    {
                        "slot": source_slot,
                        "stage": "publication",
                        "reason": "accepted response warning",
                        "items": warnings,
                    }
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
            "restaurant": config["name_ko"],
            **summary,
        }
        try:
            await notify_slack(config, notification)
        except Exception as error:
            error_type = type(error).__name__
            summary["warnings"].append(
                {
                    "stage": "notification",
                    "reason": "notification failed",
                    "error_type": error_type,
                }
            )
            emit_event(
                "WARNING",
                "notification.failed",
                "notification",
                date=meal_date,
                error_type=error_type,
            )
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
    if config["restaurant"] == "DORMITORY":
        if isinstance(request.get("target_date"), str):
            start_date = datetime.strptime(target_date, "%Y%m%d")
            requested_dates = [
                (start_date + timedelta(days=index)).strftime("%Y%m%d")
                for index in range(7)
            ]
        else:
            requested_dates = _week_dates(7, next_week=False)
        results = await _process_source_date(
            config,
            target_date,
            scheduled=False,
            requested_dates=requested_dates,
        )
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
        results = await _process_source_date(config, target_date, scheduled=False)
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
        results.extend(
            await _process_source_date(
                config, dates[0], scheduled=True, requested_dates=dates
            )
        )
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
            "restaurant": config["name_ko"],
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
    payload = _mapping(event)
    invocation_id = getattr(context, "aws_request_id", "unknown")
    run_id = request.get("execution_id") or payload.get("id") or invocation_id
    token = _observation_context.set(
        {
            "service.name": "menu-scraper",
            "faas.invocation_id": str(invocation_id),
            "run_id": str(run_id),
            "operation": operation,
            "restaurant": config["restaurant"],
            "trigger": request["trigger"],
        }
    )
    try:
        emit_event("INFO", "handler.invocation.started", "handler")
        response = await dispatcher(config, request, event)
        emit_event("INFO", "handler.invocation.completed", "handler")
        return response
    except (RetryableEmptyMenuError, RetryableApiSendError) as error:
        emit_event(
            "WARNING",
            "handler.invocation.retryable",
            "handler",
            error_type=type(error).__name__,
        )
        raise
    except Exception as error:
        emit_event(
            "ERROR",
            "handler.invocation.failed",
            "handler",
            error_type=type(error).__name__,
        )
        raise
    finally:
        _observation_context.reset(token)


def lambda_handler(event: object, context: object) -> dict[str, Any]:
    return asyncio.run(orchestrate(event, context))
