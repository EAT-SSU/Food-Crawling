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
_SCHEDULE_MODES = frozenset({"next_week", "current_week", "remaining_week"})
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


class RetryableMenuInterpretationError(Exception):
    """Signal Step Functions that model output validation should be retried."""

    def __init__(
        self,
        target_date: str,
        restaurant: str = "DORMITORY",
        reason_code: str = "VALIDATION_FAILED",
    ) -> None:
        super().__init__("retryable menu interpretation failure")
        self.target_date = target_date
        self.restaurant = restaurant
        self.reason_code = reason_code


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.lower() == "true"


def _date(value: object) -> str | None:
    return value if isinstance(value, str) and _DATE_PATTERN.fullmatch(value) else None


def _schedule_anchor(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


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
    raw_delayed = payload.get("delayed_schedule", query.get("delayed_schedule"))
    execution_id = payload.get("execution_id")
    raw_schedule_mode = payload.get("schedule_mode", query.get("schedule_mode"))
    schedule_mode = (
        raw_schedule_mode
        if isinstance(raw_schedule_mode, str) and raw_schedule_mode in _SCHEDULE_MODES
        else None
    )
    retry_count = _retry_count(payload.get("retry_count", 0))
    schedule_anchor = _schedule_anchor(payload.get("schedule_anchor"))
    delayed = _boolean(raw_delayed)
    if (
        not delayed
        and retry_count > 0
        and schedule_mode == "next_week"
        and schedule_anchor is not None
    ):
        anchor_date = datetime.fromisoformat(
            schedule_anchor.replace("Z", "+00:00")
        ).astimezone(ZoneInfo("Asia/Seoul")).date()
        delayed = _now_seoul().date() > anchor_date
    if delayed and schedule_mode in {None, "next_week"}:
        schedule_mode = "current_week"
    raw_notify_summary = payload.get(
        "notify_summary", query.get("notify_summary", True)
    )
    return {
        "trigger": raw_trigger if raw_trigger in _TRIGGERS else "direct",
        "delayed_schedule": delayed,
        "execution_id": execution_id
        if isinstance(execution_id, str) and execution_id
        else None,
        "retry_count": retry_count,
        "target_date": _date(
            payload.get("target_date") or payload.get("date") or query.get("date")
        ),
        "schedule_mode": schedule_mode,
        "notify_summary": (
            raw_notify_summary if isinstance(raw_notify_summary, bool) else True
        ),
        "schedule_anchor": schedule_anchor,
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


def load_restaurant_config(restaurant: object) -> Mapping[str, Any] | None:
    """Resolve allowlisted restaurant metadata without loading runtime secrets."""
    config_module = importlib.import_module("functions.config")
    loaded = config_module.load_restaurant_config(restaurant)
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


async def meal_exists(
    config: Mapping[str, Any],
    time_slot: str,
    environment: str,
    *,
    target_date: str,
) -> bool:
    module = importlib.import_module("functions.clients")
    base_url_key = "api_base_url" if environment == "prod" else "dev_api_base_url"
    return await module.spring_meal_exists(
        base_url=config[base_url_key],
        environment=environment,
        date=target_date,
        restaurant=config["restaurant"],
        time=time_slot,
    )


async def publish_if_missing(
    config: Mapping[str, Any], payload: Mapping[str, Any], environment: str
) -> Any | None:
    if await meal_exists(
        config,
        str(payload["time"]),
        environment,
        target_date=str(payload["date"]),
    ):
        return None
    return await publish_menu(config, payload, environment)


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


def _now_seoul() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _request_now(request: Mapping[str, Any]) -> datetime:
    if request.get("delayed_schedule") is True:
        return _now_seoul()
    anchor = request.get("schedule_anchor")
    if isinstance(anchor, str):
        return datetime.fromisoformat(anchor.replace("Z", "+00:00")).astimezone(
            ZoneInfo("Asia/Seoul")
        )
    return _now_seoul()


def _week_dates(
    day_count: int, *, next_week: bool, now: datetime | None = None
) -> list[str]:
    current = (now or _now_seoul()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday = current - timedelta(days=current.weekday())
    if next_week:
        monday += timedelta(days=7)
    return [(monday + timedelta(days=index)).strftime("%Y%m%d") for index in range(day_count)]


def _dates_for(config: Mapping[str, Any], request: Mapping[str, Any]) -> list[str]:
    target_date = request.get("target_date")
    if isinstance(target_date, str):
        return [target_date]
    schedule_mode = request.get("schedule_mode")
    now = _request_now(request)
    if schedule_mode == "remaining_week":
        week_dates = _week_dates(
            int(config["week_days"]), next_week=False, now=now
        )
        today = now.strftime("%Y%m%d")
        return [date for date in week_dates if date >= today]
    if schedule_mode in {"current_week", "next_week"}:
        return _week_dates(
            int(config["week_days"]),
            next_week=schedule_mode == "next_week",
            now=now,
        )
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


def _slot_times(config: Mapping[str, Any]) -> tuple[str, ...]:
    times: list[str] = []
    for policy in _mapping(config.get("slots")).values():
        if not isinstance(policy, Sequence) or isinstance(policy, (str, bytes)):
            continue
        if not policy:
            continue
        time_slot = str(policy[0])
        if time_slot not in times:
            times.append(time_slot)
    return tuple(times)


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


def _main_menus(
    interpreted: Mapping[str, Any], menu_names: Sequence[str]
) -> list[dict[str, str]]:
    value = interpreted.get("mainMenus")
    if not isinstance(value, list):
        return []

    validated: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"nameKo", "nameEn"}:
            continue
        name_ko = item["nameKo"]
        name_en = item["nameEn"]
        if (
            isinstance(name_ko, str)
            and name_ko in menu_names
            and isinstance(name_en, str)
            and name_en.strip()
        ):
            validated.append({"nameKo": name_ko, "nameEn": name_en})
    return validated


async def _process_source_date(
    config: Mapping[str, Any],
    target_date: str,
    *,
    scheduled: bool,
    requested_dates: Sequence[str] | None = None,
    notify_summary: bool = True,
    retry_failures: bool = True,
    known_present: set[tuple[str, str, str]] | None = None,
    blocked_publications: set[tuple[str, str, str]] | None = None,
    expected_empty: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    workflow_retry = scheduled and retry_failures
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
        if workflow_retry and outcome == "AMBIGUOUS_EMPTY":
            raise RetryableEmptyMenuError(target_date, config["restaurant"]) from None
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
    if scheduled and requested_dates is not None:
        represented_dates = {
            meal_date
            for raw_meal in raw_meals
            if (meal_date := _date(raw_meal.get("date"))) is not None
        }
        missing_dates = set(requested_dates) - represented_dates
        if workflow_retry and missing_dates:
            raise RetryableEmptyMenuError(target_date, config["restaurant"])
        raw_meals.extend(
            {
                "date": missing_date,
                "source_slot": "전체",
                "raw_text": "",
                "source_english": (),
                "outcome": "AMBIGUOUS_EMPTY",
                "reason_code": "MISSING_DATE",
            }
            for missing_date in sorted(missing_dates)
        )

    summaries: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "menus": {},
            "main_menus": {},
            "warnings": [],
            "errors": [],
            "empty_reasons": {},
        }
    )
    critical_failures: set[str] = set()
    environments = ("dev", "prod") if scheduled else ("dev",)
    present = known_present if known_present is not None else set()
    blocked = blocked_publications if blocked_publications is not None else set()
    expected = expected_empty if expected_empty is not None else set()
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
            if workflow_retry and outcome == "AMBIGUOUS_EMPTY":
                raise RetryableEmptyMenuError(meal_date, config["restaurant"])
            summary["menus"][source_slot] = []
            summary["empty_reasons"][source_slot] = reason_code
            if outcome == "EXPECTED_EMPTY":
                policy = _slot_policy(config, source_slot)
                empty_times = (
                    _slot_times(config)
                    if source_slot == "전체"
                    else (policy[0],) if policy is not None else ()
                )
                expected.update((meal_date, time_slot) for time_slot in empty_times)
            if outcome == "AMBIGUOUS_EMPTY":
                summary["errors"].append(
                    {"slot": source_slot, "stage": "source", "error_type": str(reason_code)}
                )
            continue
        policy = _slot_policy(config, source_slot)
        if policy is None:
            summary["warnings"].append(
                {"slot": source_slot, "reason": "unsupported source slot"}
            )
            continue
        time_slot, price = policy
        if not scheduled:
            for environment in environments:
                publication_key = (meal_date, time_slot, environment)
                try:
                    if await meal_exists(
                        config,
                        time_slot,
                        environment,
                        target_date=meal_date,
                    ):
                        present.add(publication_key)
                except Exception:
                    blocked.add(publication_key)
        if all(
            (meal_date, time_slot, environment) in present
            for environment in environments
        ):
            continue
        try:
            interpreted = await interpret_menu(config, raw_meal)
        except (
            RetryableEmptyMenuError,
            RetryableApiSendError,
            RetryableMenuInterpretationError,
        ):
            raise
        except Exception as error:
            menu_ai_module = importlib.import_module("functions.menu_ai")
            is_validation_error = isinstance(
                error, menu_ai_module.MenuInterpretationError
            )
            if is_validation_error:
                reason_code = getattr(error, "reason_code", "VALIDATION_FAILED")
                if reason_code not in menu_ai_module.MENU_INTERPRETATION_REASON_CODES:
                    reason_code = "VALIDATION_FAILED"
                emit_event(
                    "WARNING",
                    "menu_ai.validation_failed",
                    "menu_ai",
                    date=meal_date,
                    slot=source_slot,
                    error_type="MenuInterpretationError",
                    reason_code=reason_code,
                )
                if workflow_retry:
                    raise RetryableMenuInterpretationError(
                        meal_date, config["restaurant"], reason_code
                    ) from None
            else:
                reason_code = "PROVIDER_FAILURE"
                emit_event(
                    "WARNING",
                    "menu_ai.request_failed",
                    "menu_ai",
                    date=meal_date,
                    slot=source_slot,
                    error_type="MenuProviderError",
                    reason_code="PROVIDER_FAILURE",
                )
                if workflow_retry:
                    raise RetryableMenuInterpretationError(
                        meal_date, config["restaurant"], "PROVIDER_FAILURE"
                    ) from None
            summary["errors"].append(
                {
                    "slot": source_slot,
                    "stage": "menu_ai",
                    "error_type": type(error).__name__,
                    "reason_code": reason_code,
                }
            )
            continue

        menu_names = _menu_names(interpreted)
        summary["menus"][source_slot] = menu_names
        main_menus = _main_menus(interpreted, menu_names)
        if main_menus:
            summary["main_menus"][source_slot] = main_menus
        payload: dict[str, Any] = {
            "date": meal_date,
            "restaurant": config["restaurant"],
            "time": time_slot,
            "price": price,
            "menuNames": menu_names,
        }
        if main_menus:
            payload["mainMenus"] = main_menus

        for environment in environments:
            publication_key = (meal_date, time_slot, environment)
            if publication_key in present:
                continue
            if publication_key in blocked:
                summary["warnings"].append(
                    {
                        "slot": source_slot,
                        "stage": "publication",
                        "environment": environment,
                        "reason": "existence check failed",
                        "error_type": "SpringExistenceError",
                    }
                )
                if environment == critical_environment:
                    critical_failures.add(meal_date)
                continue
            try:
                publication = await publish_if_missing(
                    config, payload, environment
                )
            except (
                RetryableEmptyMenuError,
                RetryableApiSendError,
                RetryableMenuInterpretationError,
            ):
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

            present.add(publication_key)
            if publication is None:
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

    if workflow_retry and critical_failures:
        raise RetryableApiSendError(
            target_date,
            config["restaurant"],
            failed_days=len(critical_failures),
        )

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
        if notify_summary:
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
                "error_reasons": [
                    item.get("reason_code")
                    for item in summary["errors"]
                    if item.get("reason_code")
                ],
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
    environments = ("dev", "prod")
    required_times = _slot_times(config)
    known_present: set[tuple[str, str, str]] = set()
    blocked_publications: set[tuple[str, str, str]] = set()
    expected_empty: set[tuple[str, str]] = set()

    for target_date in dates:
        for time_slot in required_times:
            for environment in environments:
                try:
                    if await meal_exists(
                        config,
                        time_slot,
                        environment,
                        target_date=target_date,
                    ):
                        known_present.add((target_date, time_slot, environment))
                except Exception:
                    blocked_publications.add((target_date, time_slot, environment))

    dates_to_scrape = [
        target_date
        for target_date in dates
        if any(
            not all(
                (target_date, time_slot, environment) in known_present
                for environment in environments
            )
            for time_slot in required_times
        )
    ]
    results: list[dict[str, Any]] = []
    for target_date in dates_to_scrape:
        try:
            results.extend(
                await _process_source_date(
                    config,
                    target_date,
                    scheduled=True,
                    requested_dates=(
                        [target_date]
                        if config["restaurant"] == "DORMITORY"
                        else None
                    ),
                    notify_summary=False,
                    retry_failures=False,
                    known_present=known_present,
                    blocked_publications=blocked_publications,
                    expected_empty=expected_empty,
                )
            )
        except (
            RetryableEmptyMenuError,
            RetryableApiSendError,
            RetryableMenuInterpretationError,
        ):
            raise
        except Exception as error:
            if getattr(error, "outcome", None) != "API_FAILURE":
                raise
            results.append(
                {
                    "date": target_date,
                    "restaurant": config["name_ko"],
                    "menus": {},
                    "success": False,
                    "error_slots": {"전체": "SOURCE_HTTP_ERROR"},
                    "error_reasons": ["SOURCE_HTTP_ERROR"],
                    "warnings": [
                        {
                            "slot": "전체",
                            "stage": "source",
                            "error_type": type(error).__name__,
                        }
                    ],
                }
            )

    remaining_missing: list[dict[str, Any]] = []
    secured = 0
    expected_empty_count = 0
    for target_date in dates:
        for time_slot in required_times:
            if (target_date, time_slot) in expected_empty:
                expected_empty_count += 1
                secured += 1
                continue
            missing_environments = [
                environment
                for environment in environments
                if (target_date, time_slot, environment) not in known_present
            ]
            if missing_environments:
                remaining_missing.append(
                    {
                        "date": target_date,
                        "time": time_slot,
                        "environments": missing_environments,
                    }
                )
            else:
                secured += 1

    completeness = {
        "secured": secured,
        "total": len(dates) * len(required_times),
        "expected_empty": expected_empty_count,
    }
    body = {
        "results": results,
        "remaining_missing": remaining_missing,
        "completeness": completeness,
    }
    if not remaining_missing:
        return _response(200, body)

    if config["restaurant"] == "DORMITORY":
        today = _now_seoul().strftime("%Y%m%d")
        today_missing = [
            item for item in remaining_missing if item["date"] == today
        ]
        if request["notify_summary"] and today_missing:
            await notify_slack(
                config,
                {
                    "type": "weekly_completeness",
                    "date": dates[0],
                    "restaurant": config["name_ko"],
                    "completeness": completeness,
                    "remaining_missing": today_missing,
                },
            )
        return _response(200, body)

    if request["schedule_mode"] != "next_week":
        return _response(200, body)

    if request["retry_count"] >= 9:
        if request["notify_summary"]:
            await notify_slack(
                config,
                {
                    "type": "weekly_completeness",
                    "date": dates[0],
                    "restaurant": config["name_ko"],
                    "completeness": completeness,
                    "remaining_missing": remaining_missing,
                },
            )
        return _response(200, body)

    has_publication_failure = bool(blocked_publications) or any(
        any(
            warning.get("stage") == "publication"
            for warning in result.get("warnings", [])
            if isinstance(warning, Mapping)
        )
        for result in results
    )
    if has_publication_failure:
        raise RetryableApiSendError(
            dates[0], config["restaurant"], failed_days=len(remaining_missing)
        )
    has_interpretation_failure = any(
        any(str(error).endswith("Error") for error in result["error_slots"].values())
        for result in results
    )
    if has_interpretation_failure:
        reason_code = next(
            (
                reason
                for result in results
                for reason in result.get("error_reasons", [])
                if reason in {"PROVIDER_FAILURE", "VALIDATION_FAILED"}
            ),
            "VALIDATION_FAILED",
        )
        raise RetryableMenuInterpretationError(
            dates[0], config["restaurant"], reason_code
        )
    raise RetryableEmptyMenuError(dates[0], config["restaurant"])


async def _run_final_failure(
    config: Mapping[str, Any], request: Mapping[str, Any], event: object
) -> dict[str, Any]:
    payload = _mapping(event)
    raw_error_type = payload.get("error_type")
    known_errors = {
        "RetryableEmptyMenuError",
        "RetryableApiSendError",
        "RetryableMenuInterpretationError",
        "Lambda.ServiceException",
        "Lambda.AWSLambdaException",
        "Lambda.SdkClientException",
        "Lambda.TooManyRequestsException",
    }
    error_type = raw_error_type if raw_error_type in known_errors else "UnknownError"
    restaurant_metadata = load_restaurant_config(payload.get("restaurant")) or config
    notification_config = {**config, **restaurant_metadata}
    target_date = _dates_for(notification_config, request)[0]
    await notify_slack(
        notification_config,
        {
            "type": "final_failure",
            "date": target_date,
            "restaurant": notification_config["name_ko"],
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
    context_config = (
        load_restaurant_config(payload.get("restaurant")) or config
        if operation == "notify_final_failure"
        else config
    )
    invocation_id = getattr(context, "aws_request_id", "unknown")
    run_id = request.get("execution_id") or payload.get("id") or invocation_id
    token = _observation_context.set(
        {
            "service.name": "menu-scraper",
            "faas.invocation_id": str(invocation_id),
            "run_id": str(run_id),
            "operation": operation,
            "restaurant": context_config["restaurant"],
            "trigger": request["trigger"],
        }
    )
    try:
        emit_event("INFO", "handler.invocation.started", "handler")
        response = await dispatcher(config, request, event)
        emit_event("INFO", "handler.invocation.completed", "handler")
        return response
    except (
        RetryableEmptyMenuError,
        RetryableApiSendError,
        RetryableMenuInterpretationError,
    ) as error:
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
