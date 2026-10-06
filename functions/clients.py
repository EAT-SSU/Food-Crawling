import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


_HTTP_TIMEOUT_SECONDS = 10
_SAFE_EMPTY_REASONS = {
    "HOLIDAY": "휴무일",
    "WEEKEND_CLOSED": "주말 미운영",
    "CLOSED_MARKER": "미운영",
    "SOURCE_EMPTY": "메뉴 미게시 또는 원본 누락",
    "SOURCE_SCHEMA_CHANGED": "메뉴 원본 구조 변경",
    "MISSING_DATE_HEADER": "메뉴 원본 구조 변경",
    "MISSING_DATE_CELL": "메뉴 원본 구조 변경",
    "MISSING_SLOT_COLUMN": "메뉴 원본 구조 변경",
    "EMPTY_CELL": "메뉴 미게시 또는 원본 누락",
}

_SAFE_STAGE_REASONS = {
    "menu_ai": "메뉴 파싱 실패",
    "parsing": "메뉴 파싱 실패",
    "source": "메뉴 원본 확인 필요",
    "publication": "메뉴 저장 실패",
    "unmatched": "대표메뉴 매칭 실패",
}

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


def format_slack_text(notification: Mapping[str, object]) -> str:
    """Render only allowlisted orchestration fields for Slack."""
    notification_type = notification.get("type")
    raw_date = notification.get("date")
    date = (
        raw_date
        if isinstance(raw_date, str) and re.fullmatch(r"\d{8}", raw_date)
        else "unknown"
    )
    restaurant = _safe_display(notification.get("restaurant")) or "식당"
    header = f"🍽️ {restaurant} ({date})"
    if notification_type == "final_failure":
        allowed_errors = {
            "RetryableEmptyMenuError": "메뉴 미게시",
            "RetryableApiSendError": "메뉴 저장 실패",
            "RetryableMenuInterpretationError": "메뉴 파싱 실패",
            "Lambda.ServiceException": "Lambda 서비스 오류",
            "Lambda.AWSLambdaException": "Lambda 실행 오류",
            "Lambda.SdkClientException": "Lambda 호출 오류",
            "Lambda.TooManyRequestsException": "Lambda 요청 제한",
        }
        raw_error_type = notification.get("error_type")
        error_type = raw_error_type if isinstance(raw_error_type, str) else "UnknownError"
        reason = allowed_errors.get(error_type, "알 수 없는 처리 오류")
        return f"{header}\n⚠️ 최종 처리 실패: {reason}"
    if notification_type == "weekly_completeness":
        completeness = notification.get("completeness")
        values = completeness if isinstance(completeness, Mapping) else {}

        def safe_count(name: str) -> int:
            value = values.get(name)
            return (
                value
                if isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
                else 0
            )

        secured = safe_count("secured")
        total = safe_count("total")
        expected_empty = safe_count("expected_empty")
        missing = notification.get("remaining_missing")
        missing_count = len(missing) if isinstance(missing, list) else 0
        return (
            f"{header}\n"
            f"⚠️ 주간 메뉴 확보: {secured}/{total}개 (미운영 {expected_empty}개)\n"
            f"⚠️ 마감 시점 미확보: {missing_count}개"
        )
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
    menus = notification.get("menus")
    main_menus = notification.get("main_menus")
    empty_reasons = notification.get("empty_reasons")
    if (
        isinstance(empty_reasons, Mapping)
        and empty_reasons.get("전체") == "HOLIDAY"
    ):
        return f"{header}\nℹ️ 휴무일"
    if (
        isinstance(empty_reasons, Mapping)
        and empty_reasons.get("전체") == "WEEKEND_CLOSED"
    ):
        return f"{header}\nℹ️ 주말 미운영"

    statuses: list[str] = []
    status_keys: set[tuple[str | None, str]] = set()
    error_slots: set[str] = set()
    for field in ("errors", "warnings"):
        entries = notification.get(field)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            raw_stage = entry.get("stage")
            stage = raw_stage if isinstance(raw_stage, str) else ""
            reason = _SAFE_STAGE_REASONS.get(stage)
            if reason is None:
                continue
            slot = _safe_display(entry.get("slot"))
            key = (slot, reason)
            if key in status_keys:
                continue
            status_keys.add(key)
            if slot:
                error_slots.add(slot)
            statuses.append(f"⚠️ {slot}: {reason}" if slot else f"⚠️ {reason}")

    safe_lines = [header]
    empty_slots = set(empty_reasons) if isinstance(empty_reasons, Mapping) else set()
    if isinstance(menus, Mapping):
        for raw_slot, items in sorted(menus.items(), key=lambda item: str(item[0])):
            slot = _safe_display(raw_slot)
            if not slot or not isinstance(items, list) or slot in empty_slots:
                continue
            safe_items = [
                safe_item
                for item in items
                if (safe_item := _safe_display(item)) is not None
            ]
            if safe_items:
                safe_lines.append(f"• {slot}: {', '.join(safe_items)}")
                raw_representatives = (
                    main_menus.get(raw_slot) if isinstance(main_menus, Mapping) else None
                )
                safe_representatives: list[str] = []
                if isinstance(raw_representatives, list):
                    for representative in raw_representatives:
                        if (
                            not isinstance(representative, Mapping)
                            or set(representative) != {"nameKo", "nameEn"}
                        ):
                            continue
                        raw_name_ko = representative["nameKo"]
                        raw_name_en = representative["nameEn"]
                        if not isinstance(raw_name_ko, str) or not isinstance(
                            raw_name_en, str
                        ):
                            continue
                        name_ko = _safe_display(raw_name_ko)
                        name_en = _safe_display(raw_name_en)
                        if name_ko in safe_items and name_en is not None:
                            safe_representatives.append(f"{name_ko} ({name_en})")
                if safe_representatives:
                    safe_lines.append(f"  ↳ 대표: {', '.join(safe_representatives)}")

    if isinstance(empty_reasons, Mapping):
        for raw_slot, raw_reason_code in sorted(
            empty_reasons.items(), key=lambda item: str(item[0])
        ):
            slot = _safe_display(raw_slot)
            reason_code = raw_reason_code if isinstance(raw_reason_code, str) else ""
            if slot and slot not in error_slots:
                safe_lines.append(
                    f"ℹ️ {slot}: {_SAFE_EMPTY_REASONS.get(reason_code, '메뉴 원본 확인 필요')}"
                )
    safe_lines.extend(statuses)
    return "\n".join(safe_lines)
