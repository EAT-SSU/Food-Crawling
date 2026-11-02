import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


_HTTP_TIMEOUT_SECONDS = 10
_UNSAFE_DISPLAY_PATTERN = re.compile(
    r"<|>|://|www\.|critical|cause|secret|exception|traceback|provider\.",
    re.IGNORECASE,
)


def _safe_display(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if (
        not normalized
        or _UNSAFE_DISPLAY_PATTERN.search(normalized)
    ):
        return None
    return normalized


class SpringSlotReplaceError(RuntimeError):
    """A Spring slot replacement failed."""


class SpringExistenceError(RuntimeError):
    """A Spring existence request could not be interpreted safely."""


class SlackNotificationError(RuntimeError):
    """A Slack webhook request failed."""


@retry(
    retry=retry_if_exception_type(SpringExistenceError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise=True,
)
async def spring_existing_meals(
    *,
    base_url: str,
    environment: str,
    date: str,
    restaurant: str,
    time: str,
) -> list[list[str]]:
    url = f"{base_url.rstrip('/')}/meals"
    params = {
        "date": date,
        "restaurant": restaurant,
        "time": time,
        "language": "KO",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS),
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise SpringExistenceError(
                        f"Spring {environment} meal existence check failed"
                    )
                response_body = await response.text()
        decoded = json.loads(response_body)
        if (
            not isinstance(decoded, dict)
            or decoded.get("isSuccess") is not True
            or not isinstance(decoded.get("result"), list)
        ):
            raise SpringExistenceError(
                f"Spring {environment} meal existence check failed"
            )
        meals: list[list[str]] = []
        for meal in decoded["result"]:
            if not isinstance(meal, dict) or not isinstance(
                meal.get("briefMenus"), list
            ):
                raise SpringExistenceError(
                    f"Spring {environment} meal existence check failed"
                )
            names: list[str] = []
            for menu in meal["briefMenus"]:
                if not isinstance(menu, dict) or not isinstance(menu.get("name"), str):
                    raise SpringExistenceError(
                        f"Spring {environment} meal existence check failed"
                    )
                names.append(menu["name"])
            meals.append(names)
        return meals
    except SpringExistenceError:
        raise
    except Exception as error:
        raise SpringExistenceError(
            f"Spring {environment} meal existence check failed"
        ) from error


@dataclass(frozen=True)
class SpringSlotReplaceResult:
    meal_ids: Tuple[object, ...]
    unmatched_main_menus: Tuple[Tuple[Mapping[str, object], ...], ...]
    deleted_meal_ids: Tuple[object, ...]
    kept_with_reviews: Tuple[object, ...]


def _parse_slot_replace_response(body: str) -> SpringSlotReplaceResult:
    try:
        decoded = json.loads(body)
        result = decoded["result"]
        meal_ids = result["mealIds"]
        unmatched = result["unmatchedMainMenus"]
        deleted = result["deletedMealIds"]
        kept = result["keptWithReviews"]
        if (
            decoded.get("isSuccess") is not True
            or not isinstance(result, dict)
            or not isinstance(meal_ids, list)
            or not isinstance(unmatched, list)
            or not all(
                isinstance(items, list)
                and all(isinstance(item, dict) for item in items)
                for items in unmatched
            )
            or not isinstance(deleted, list)
            or not isinstance(kept, list)
        ):
            raise ValueError("invalid response")
    except (KeyError, TypeError, ValueError) as error:
        raise SpringSlotReplaceError("Spring slot replacement failed") from error
    return SpringSlotReplaceResult(
        meal_ids=tuple(meal_ids),
        unmatched_main_menus=tuple(tuple(items) for items in unmatched),
        deleted_meal_ids=tuple(deleted),
        kept_with_reviews=tuple(kept),
    )


@retry(
    retry=retry_if_exception_type(SpringSlotReplaceError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise=True,
)
async def replace_spring_slot(
    *,
    base_url: str,
    environment: str,
    date: str,
    restaurant: str,
    time: str,
    items: Sequence[Mapping[str, object]],
) -> SpringSlotReplaceResult:
    url = f"{base_url.rstrip('/')}/meals/with-price/slot"
    params = {"date": date, "restaurant": restaurant, "time": time}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url,
                json=list(items),
                params=params,
                timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS),
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise SpringSlotReplaceError(
                        f"Spring {environment} slot replacement failed"
                    )
                response_body = await response.text()
    except SpringSlotReplaceError:
        raise
    except Exception as error:
        raise SpringSlotReplaceError(
            f"Spring {environment} slot replacement failed"
        ) from error

    return _parse_slot_replace_response(response_body)


@retry(
    retry=retry_if_exception_type(SlackNotificationError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise=True,
)
async def send_slack_text(*, webhook_url: str, text: str) -> None:
    payload = {
        "username": "학식봇",
        "text": text,
        "icon_emoji": ":fork_and_knife:",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS),
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise SlackNotificationError("Slack notification failed")
    except SlackNotificationError:
        raise
    except Exception as error:
        raise SlackNotificationError("Slack notification failed") from error


def _representatives(raw: object, safe_items: Sequence[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    rendered: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"nameKo", "nameEn"}:
            continue
        name_ko = _safe_display(item["nameKo"])
        name_en = _safe_display(item["nameEn"])
        if name_ko in safe_items and name_en is not None:
            rendered.append(f"{name_ko} ({name_en})")
    return rendered


def format_slack_text(notification: Mapping[str, object]) -> str:
    """Render one of three allowlisted notification kinds for Slack."""
    notification_type = notification.get("type")
    raw_date = notification.get("date")
    date = (
        raw_date
        if isinstance(raw_date, str) and re.fullmatch(r"\d{8}", raw_date)
        else "unknown"
    )
    restaurant = _safe_display(notification.get("restaurant")) or "식당"
    if notification_type == "missing_on_final":
        lines = [f"🚨 {restaurant}: 마감 시점까지 발행되지 않은 코너"]
        missing = notification.get("missing")
        for entry in missing if isinstance(missing, list) else []:
            if not isinstance(entry, Mapping):
                continue
            entry_date = entry.get("date")
            if not isinstance(entry_date, str) or not re.fullmatch(r"\d{8}", entry_date):
                continue
            time_slot = entry.get("time")
            if not isinstance(time_slot, str) or not re.fullmatch(r"[A-Z]+", time_slot):
                continue
            corner = entry.get("corner")
            corner_label = (
                corner
                if isinstance(corner, str) and re.fullmatch(r"[가-힣0-9]{1,8}", corner)
                else "코너"
            )
            environment = "prod" if entry.get("environment") == "prod" else "dev"
            lines.append(f"• {entry_date} {time_slot} {corner_label} ({environment})")
        return "\n".join(lines)

    header = f"🍽️ {restaurant} ({date})"
    if notification_type == "kept_with_reviews":
        time_slot = _safe_display(notification.get("time")) or "시간대"
        raw_ids = notification.get("meal_ids")
        meal_ids = (
            [str(meal_id) for meal_id in raw_ids if isinstance(meal_id, (int, str))]
            if isinstance(raw_ids, list)
            else []
        )
        return (
            f"{header}\n"
            f"⚠️ {time_slot}: 리뷰가 있어 유지된 식단 {', '.join(meal_ids)}"
        )

    lines = [header]
    menus = notification.get("menus")
    main_menus = notification.get("main_menus")
    representatives_by_slot = main_menus if isinstance(main_menus, Mapping) else {}
    if isinstance(menus, Mapping):
        for raw_slot, items in sorted(menus.items(), key=lambda item: str(item[0])):
            slot = _safe_display(raw_slot)
            if not slot or not isinstance(items, list):
                continue
            safe_items = [
                safe_item for item in items if (safe_item := _safe_display(item)) is not None
            ]
            if not safe_items:
                continue
            lines.append(f"• {slot}: {', '.join(safe_items)}")
            representatives = _representatives(
                representatives_by_slot.get(raw_slot), safe_items
            )
            if representatives:
                lines.append(f"  ↳ 대표: {', '.join(representatives)}")
    return "\n".join(lines)
