import json
import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


_HTTP_TIMEOUT_SECONDS = 10
_RESPONSE_PARSE_WARNING = "Spring accepted the meal but returned malformed JSON"

_SAFE_EMPTY_REASONS = {
    "HOLIDAY": "휴무일",
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


class SpringPublishError(RuntimeError):
    """A Spring request failed before it was known to be accepted."""


class SlackNotificationError(RuntimeError):
    """A Slack webhook request failed."""


@dataclass(frozen=True)
class SpringPublishResult:
    accepted: bool
    unmatched_main_menus: Tuple[Mapping[str, object], ...] = ()
    warnings: Tuple[str, ...] = ()


def _main_menu_body(
    menu_names: Sequence[str],
    main_menus: Optional[Sequence[Mapping[str, str]]],
) -> list[dict[str, str]]:
    if not main_menus:
        return []

    validated: list[dict[str, str]] = []
    for main_menu in main_menus:
        if set(main_menu) != {"nameKo", "nameEn"}:
            raise ValueError("mainMenus entries require only nameKo and nameEn")
        name_ko = main_menu["nameKo"]
        name_en = main_menu["nameEn"]
        if (
            not isinstance(name_ko, str)
            or not name_ko
            or name_ko not in menu_names
            or not isinstance(name_en, str)
            or not name_en.strip()
        ):
            raise ValueError("mainMenus entries must be validated and non-empty")
        validated.append({"nameKo": name_ko, "nameEn": name_en})
    return validated


def _parse_spring_response(body: str) -> SpringPublishResult:
    if not body.strip():
        return SpringPublishResult(accepted=True)

    try:
        decoded = json.loads(body)
    except (TypeError, ValueError):
        return SpringPublishResult(
            accepted=True,
            warnings=(_RESPONSE_PARSE_WARNING,),
        )

    if not isinstance(decoded, dict):
        return SpringPublishResult(
            accepted=True,
            warnings=(_RESPONSE_PARSE_WARNING,),
        )

    unmatched = decoded.get("unmatchedMainMenus", [])
    if not isinstance(unmatched, list) or not all(
        isinstance(entry, dict) for entry in unmatched
    ):
        return SpringPublishResult(
            accepted=True,
            warnings=(_RESPONSE_PARSE_WARNING,),
        )

    return SpringPublishResult(
        accepted=True,
        unmatched_main_menus=tuple(unmatched),
    )


@retry(
    retry=retry_if_exception_type(SpringPublishError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise=True,
)
async def publish_spring_meal(
    *,
    base_url: str,
    environment: str,
    date: str,
    restaurant: str,
    time: str,
    menu_names: Sequence[str],
    price: int,
    main_menus: Optional[Sequence[Mapping[str, str]]] = None,
) -> SpringPublishResult:
    body: dict[str, object] = {
        "price": price,
        "menuNames": list(menu_names),
    }
    validated_main_menus = _main_menu_body(menu_names, main_menus)
    if validated_main_menus:
        body["mainMenus"] = validated_main_menus

    url = f"{base_url.rstrip('/')}/meals/with-price"
    params = {"date": date, "restaurant": restaurant, "time": time}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=body,
                params=params,
                timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS),
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise SpringPublishError(
                        f"Spring {environment} meal publication failed"
                    )
                response_body = await response.text()
    except SpringPublishError:
        raise
    except Exception as error:
        raise SpringPublishError(
            f"Spring {environment} meal publication failed"
        ) from error

    return _parse_spring_response(response_body)


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
            "Lambda.ServiceException": "Lambda 서비스 오류",
            "Lambda.AWSLambdaException": "Lambda 실행 오류",
            "Lambda.SdkClientException": "Lambda 호출 오류",
            "Lambda.TooManyRequestsException": "Lambda 요청 제한",
        }
        raw_error_type = notification.get("error_type")
        error_type = raw_error_type if isinstance(raw_error_type, str) else "UnknownError"
        reason = allowed_errors.get(error_type, "알 수 없는 처리 오류")
        return f"{header}\n⚠️ 최종 처리 실패: {reason}"

    menus = notification.get("menus")
    empty_reasons = notification.get("empty_reasons")
    if (
        isinstance(empty_reasons, Mapping)
        and empty_reasons.get("전체") == "HOLIDAY"
    ):
        return f"{header}\nℹ️ 휴무일"

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
