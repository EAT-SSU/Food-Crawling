"""Scrape one restaurant, interpret new corners, and publish whole Spring slots.

Re-running is always safe: every slot is read with GET first and replaced with
one whole-slot PUT, so retries are plain repeated schedule runs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from functions.clients import (
    format_slack_text,
    replace_spring_slot,
    send_slack_text,
    spring_existing_meals,
)
from functions.config import load_config
from functions.menu_ai import interpret_menu
from functions.scraper import EXPECTED_EMPTY, SUCCESS, ScraperError, fetch_meals


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

KST = ZoneInfo("Asia/Seoul")
_DATE_PATTERN = re.compile(r"\d{8}")
_DATE_MODES = frozenset({"current_week", "next_week", "remaining_week"})
_ENVIRONMENTS = ("dev", "prod")
_WHOLE_DAY = "전체"


def _now_seoul() -> datetime:
    return datetime.now(KST)


@dataclass(frozen=True)
class Corner:
    date: str
    time: str
    slot: str
    raw_text: str
    source_english: tuple[str, ...]
    price: int


@dataclass
class Run:
    config: Mapping[str, Any]
    request: Mapping[str, Any]
    covered: set[tuple[str, str, str, str]] = field(default_factory=set)
    changed_dates: set[str] = field(default_factory=set)
    menus: dict[str, dict[str, list[str]]] = field(default_factory=lambda: defaultdict(dict))
    main_menus: dict[str, dict[str, list[dict[str, str]]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    interpretations: dict[tuple[str, str], dict[str, Any] | None] = field(default_factory=dict)
    planned: list[dict[str, Any]] = field(default_factory=list)
    published: list[dict[str, Any]] = field(default_factory=list)


def parse_event(event: object) -> dict[str, Any] | str:
    payload = event if isinstance(event, Mapping) else {}
    restaurant = payload.get("restaurant")
    if not isinstance(restaurant, str) or not restaurant:
        return "missing restaurant"
    date = payload.get("date")
    dates = payload.get("dates")
    if date is not None:
        if not isinstance(date, str) or not _DATE_PATTERN.fullmatch(date):
            return "invalid date"
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError:
            return "invalid date"
    elif dates not in _DATE_MODES:
        return "missing or invalid dates"
    mode = payload.get("mode", "fill")
    if mode not in ("fill", "force"):
        return "invalid mode"
    environments = payload.get("environments", ["dev"])
    if (
        not isinstance(environments, list)
        or not environments
        or any(environment not in _ENVIRONMENTS for environment in environments)
    ):
        return "invalid environments"
    for flag in ("final", "dry_run"):
        if not isinstance(payload.get(flag, False), bool):
            return f"invalid {flag}"
    return {
        "restaurant": restaurant.upper(),
        "date": date,
        "dates": None if date is not None else dates,
        "mode": mode,
        "final": payload.get("final", False),
        "dry_run": payload.get("dry_run", False),
        "environments": [env for env in _ENVIRONMENTS if env in environments],
    }


def target_dates(request: Mapping[str, Any], week_days: int, now: datetime) -> list[str]:
    today = now.strftime("%Y%m%d")
    if request["date"] is not None:
        candidates = [request["date"]]
    else:
        monday = now.date() - timedelta(days=now.weekday())
        if request["dates"] == "next_week":
            monday += timedelta(days=7)
        candidates = [
            (monday + timedelta(days=index)).strftime("%Y%m%d") for index in range(week_days)
        ]
    return [date for date in candidates if date >= today]


def _slot_policy(config: Mapping[str, Any], source_slot: object) -> tuple[str, int] | None:
    if not isinstance(source_slot, str):
        return None
    for marker, (time_slot, price) in config["slots"].items():
        if marker in source_slot:
            return str(time_slot), int(price)
    return None


def _slot_times(config: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(policy[0]) for policy in config["slots"].values()))


def _normalized_hangul(value: str) -> str:
    return re.sub(r"[^가-힣ㄱ-ㅎㅏ-ㅣ]", "", value)


def _existing_meal_score(menu_names: Sequence[str], raw_text: str) -> float:
    normalized_names = [
        normalized for menu_name in menu_names if (normalized := _normalized_hangul(menu_name))
    ]
    if not normalized_names:
        return 0.0
    normalized_raw = _normalized_hangul(raw_text)
    matched = sum(name in normalized_raw for name in normalized_names)
    return matched / len(normalized_names)


def match_existing(meals: Sequence[list[str]], corners: Sequence[Corner]) -> dict[int, list[str]]:
    candidates = sorted(
        (-score, corner_index, meal_index)
        for corner_index, corner in enumerate(corners)
        for meal_index, names in enumerate(meals)
        if (score := _existing_meal_score(names, corner.raw_text)) >= 0.5
    )
    assigned: dict[int, list[str]] = {}
    used_meals: set[int] = set()
    for _, corner_index, meal_index in candidates:
        if corner_index in assigned or meal_index in used_meals:
            continue
        assigned[corner_index] = list(meals[meal_index])
        used_meals.add(meal_index)
    return assigned


def _signature(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(names))


async def collect_sources(
    config: Mapping[str, Any], dates: Sequence[str]
) -> tuple[dict[tuple[str, str], list[Corner]], dict[tuple[str, str], str]]:
    restaurant = config["restaurant"]
    if restaurant == "DORMITORY":
        weeks: dict[str, list[str]] = defaultdict(list)
        for date in dates:
            day = datetime.strptime(date, "%Y%m%d")
            weeks[(day - timedelta(days=day.weekday())).strftime("%Y%m%d")].append(date)
        groups = list(weeks.values())
    else:
        groups = [[date] for date in dates]

    records: list[Any] = []
    closed: set[str] = set()
    failed: set[str] = set()
    for group in groups:
        try:
            records.extend(await fetch_meals(restaurant, group[0], requested_dates=group))
        except ScraperError as error:
            if error.outcome == EXPECTED_EMPTY:
                closed.update(group)
                continue
            logger.warning(
                "source unavailable restaurant=%s dates=%s reason=%s",
                restaurant, ",".join(group), error.reason_code,
            )
            failed.update(group)

    all_times = _slot_times(config)
    unreadable: dict[tuple[str, str], str] = {}
    seen_dates = {record.date for record in records}
    for date in dates:
        if date in failed or (date not in seen_dates and date not in closed):
            unreadable.update({(date, time_slot): _WHOLE_DAY for time_slot in all_times})

    corners: dict[tuple[str, str], list[Corner]] = defaultdict(list)
    for record in records:
        if record.date not in dates or record.outcome == EXPECTED_EMPTY:
            continue
        policy = _slot_policy(config, record.source_slot)
        if record.outcome != SUCCESS:
            times = all_times if record.source_slot == _WHOLE_DAY else (policy[0],) if policy else ()
            unreadable.update({(record.date, time_slot): record.source_slot for time_slot in times})
            continue
        if policy is None:
            logger.info("unsupported source slot date=%s slot=%s", record.date, record.source_slot)
            continue
        corners[(record.date, policy[0])].append(
            Corner(record.date, policy[0], record.source_slot, record.raw_text,
                   tuple(record.source_english), policy[1])
        )
    # A partially readable slot is never PUT: the whole-slot PUT would drop the unread corner.
    for key in unreadable:
        corners.pop(key, None)
    return dict(corners), unreadable


def _base_url(config: Mapping[str, Any], environment: str) -> str:
    return config["api_base_url"] if environment == "prod" else config["dev_api_base_url"]


async def _existing(run: Run, environment: str, date: str, time_slot: str) -> list[list[str]] | None:
    try:
        return await spring_existing_meals(
            base_url=_base_url(run.config, environment),
            environment=environment,
            date=date,
            restaurant=run.config["restaurant"],
            time=time_slot,
        )
    except Exception as error:
        logger.warning(
            "spring GET failed date=%s time=%s env=%s error=%s",
            date, time_slot, environment, type(error).__name__,
        )
        return None


async def _interpret(run: Run, corner: Corner) -> dict[str, Any] | None:
    key = (corner.date, corner.slot)
    if key in run.interpretations:
        return run.interpretations[key]
    item: dict[str, Any] | None = None
    try:
        result = await interpret_menu(
            run.config["gpt_api_key"],
            run.config["restaurant"],
            corner.raw_text,
            corner.source_english,
        )
        names = [name for name in result.get("menuNames", []) if isinstance(name, str)]
        main_menus = [
            {"nameKo": main["nameKo"], "nameEn": main["nameEn"]}
            for main in result.get("mainMenus") or []
            if isinstance(main, Mapping)
            and main.get("nameKo") in names
            and isinstance(main.get("nameEn"), str)
            and main["nameEn"].strip()
        ]
        if names:
            item = {"menuNames": names, "price": corner.price, "mainMenus": main_menus}
    except Exception as error:
        logger.warning(
            "menu interpretation failed date=%s slot=%s error=%s reason=%s",
            corner.date, corner.slot, type(error).__name__, getattr(error, "reason_code", "-"),
        )
    run.interpretations[key] = item
    return item


async def _notify(run: Run, notification: Mapping[str, Any]) -> None:
    try:
        await send_slack_text(
            webhook_url=run.config["slack_webhook_url"],
            text=format_slack_text(notification),
        )
    except Exception as error:
        logger.warning(
            "slack notification failed type=%s error=%s",
            notification.get("type"), type(error).__name__,
        )


async def publish_slot(
    run: Run, date: str, time_slot: str, corners: Sequence[Corner], environment: str
) -> None:
    config = run.config
    log_key = f"date={date} time={time_slot} env={environment}"
    meals = await _existing(run, environment, date, time_slot)
    if meals is None:
        return

    fill = run.request["mode"] == "fill"
    mapped = match_existing(meals, corners) if fill else {}
    if fill and len(mapped) == len(corners) == len(meals):
        run.covered.update((date, time_slot, corner.slot, environment) for corner in corners)
        logger.info("slot unchanged %s corners=%d", log_key, len(corners))
        return

    items: list[dict[str, Any]] = []
    for index, corner in enumerate(corners):
        if index in mapped:
            item: dict[str, Any] | None = {
                "menuNames": mapped[index], "price": corner.price, "mainMenus": None
            }
        else:
            item = await _interpret(run, corner)
        if item is None:
            logger.warning("slot skipped %s reason=interpretation_failed", log_key)
            return
        run.menus[date][corner.slot] = list(item["menuNames"])
        if item["mainMenus"]:
            run.main_menus[date][corner.slot] = list(item["mainMenus"])
        items.append(item)
    # Spring rejects duplicate menu-name lists in one slot.
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in items:
        unique.setdefault(_signature(item["menuNames"]), item)
    items = list(unique.values())
    if not items:
        return
    if run.request["dry_run"]:
        run.planned.append(
            {"date": date, "time": time_slot, "environment": environment, "items": items}
        )
        logger.info("dry run planned PUT %s items=%d", log_key, len(items))
        return

    try:
        result = await replace_spring_slot(
            base_url=_base_url(config, environment),
            environment=environment,
            date=date,
            restaurant=config["restaurant"],
            time=time_slot,
            items=items,
        )
    except Exception as error:
        logger.warning("spring PUT failed %s error=%s", log_key, type(error).__name__)
        return

    run.covered.update((date, time_slot, corner.slot, environment) for corner in corners)
    deleted = list(result.deleted_meal_ids)
    if sorted(_signature(names) for names in meals) != sorted(unique) or deleted:
        run.changed_dates.add(date)
    run.published.append(
        {"date": date, "time": time_slot, "environment": environment, "items": len(items)}
    )
    logger.info("slot published %s items=%d deleted=%d", log_key, len(items), len(deleted))
    kept = list(result.kept_with_reviews)
    if kept:
        await _notify(run, {"type": "kept_with_reviews", "date": date, "time": time_slot,
                            "restaurant": config["name_ko"], "meal_ids": kept})


async def _missing_on_final(
    run: Run,
    slots: Mapping[tuple[str, str], Sequence[Corner]],
    unreadable: Mapping[tuple[str, str], str],
) -> list[dict[str, str]]:
    environment = "prod" if "prod" in run.request["environments"] else "dev"
    missing = [
        {"date": date, "time": time_slot, "corner": corner.slot, "environment": environment}
        for (date, time_slot), corners in sorted(slots.items())
        for corner in corners
        if (date, time_slot, corner.slot, environment) not in run.covered
    ]
    for (date, time_slot), label in sorted(unreadable.items()):
        # Corner count is unknown here, so any existing meal counts as published.
        if not await _existing(run, environment, date, time_slot):
            missing.append(
                {"date": date, "time": time_slot, "corner": label, "environment": environment}
            )
    return missing


async def run_pipeline(config: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    run = Run(config, request)
    dates = target_dates(request, int(config["week_days"]), _now_seoul())
    slots, unreadable = await collect_sources(config, dates) if dates else ({}, {})
    for (date, time_slot), corners in sorted(slots.items()):
        for environment in request["environments"]:
            await publish_slot(run, date, time_slot, corners, environment)

    missing: list[dict[str, str]] = []
    if request["final"] and not request["dry_run"]:
        missing = await _missing_on_final(run, slots, unreadable)
    if not request["dry_run"]:
        for date in sorted(run.changed_dates):
            await _notify(run, {"type": "date_summary", "date": date, "restaurant": config["name_ko"],
                                "menus": run.menus[date], "main_menus": run.main_menus[date]})
        if missing:
            await _notify(run, {"type": "missing_on_final", "restaurant": config["name_ko"],
                                "missing": missing})
    logger.info(
        "run finished restaurant=%s dates=%d published=%d planned=%d unreadable=%d missing=%d",
        config["restaurant"], len(dates), len(run.published), len(run.planned),
        len(unreadable), len(missing),
    )
    return {
        "restaurant": config["restaurant"],
        "dates": dates,
        "mode": request["mode"],
        "dry_run": request["dry_run"],
        "environments": request["environments"],
        "published": run.published,
        "planned": run.planned,
        "unreadable": [{"date": date, "time": time_slot} for date, time_slot in sorted(unreadable)],
        "missing": missing,
    }


def _response(status_code: int, body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event: object, context: object) -> dict[str, Any]:
    del context
    request = parse_event(event)
    if isinstance(request, str):
        return _response(400, {"success": False, "error": request})
    config = load_config(request["restaurant"])
    if config is None:
        return _response(400, {"success": False, "error": "unknown restaurant"})
    return _response(200, asyncio.run(run_pipeline(config, request)))
