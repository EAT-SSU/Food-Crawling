import json
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


_HTTP_TIMEOUT_SECONDS = 10
_RESPONSE_PARSE_WARNING = "Spring accepted the meal but returned malformed JSON"


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
