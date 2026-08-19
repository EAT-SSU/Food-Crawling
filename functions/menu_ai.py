import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionToolParam
from tenacity import retry, stop_after_attempt, wait_fixed


MODEL_ID = "gpt-5.6-luna"
TOOL_NAME = "extract_main_menus"
SITE_ENGLISH_RESTAURANTS = frozenset({"HAKSIK", "DODAM", "FACULTY"})
DORMITORY = "DORMITORY"

MENU_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Extract every Korean menu and select representative main menus by index."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "menuNames": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "mainCandidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "menuIndex": {"type": "integer", "minimum": 0},
                            "nameEn": {"type": "string", "minLength": 1},
                        },
                        "required": ["menuIndex", "nameEn"],
                    },
                },
            },
            "required": ["menuNames", "mainCandidates"],
        },
    },
}

SYSTEM_PROMPT = """You interpret Korean university cafeteria menu text.
Return only Korean menu dish names in menuNames, preserving each dish name exactly.
Exclude meal-slot labels such as 중식1, 석식1, and 조식1; all English translations or
English service labels such as Serve Kitchen; service/corner labels such as [대면코너];
decorative symbols such as ★; and duplicate entries. Never include non-food text.
Select representative main menus through mainCandidates.menuIndex; never repeat an index.
For HAKSIK, DODAM, and FACULTY, copy each nameEn verbatim from the supplied source.
For DORMITORY, provide English translations for exactly three representative menus, or all
menus when fewer than three exist. Always call extract_main_menus exactly once."""

_HANGUL_RE = re.compile(r"[\u3131-\u318e\uac00-\ud7a3]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SLOT_LABEL_RE = re.compile(r"^(?:조식|중식|석식)\s*\d*$")
_BRACKETED_LABEL_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")


class MenuInterpretationError(ValueError):
    """The model response does not satisfy the menu interpretation contract."""


class MainMenu(TypedDict):
    nameKo: str
    nameEn: str


class MenuInterpretation(TypedDict):
    menuNames: list[str]
    mainMenus: list[MainMenu]


def _restaurant_name(restaurant: object) -> str:
    if isinstance(restaurant, str):
        name = restaurant
    else:
        name = getattr(restaurant, "english_name", None)
    if not isinstance(name, str):
        raise MenuInterpretationError("restaurant must identify a supported restaurant")
    name = name.upper()
    if name not in SITE_ENGLISH_RESTAURANTS | {DORMITORY}:
        raise MenuInterpretationError(f"unsupported restaurant: {name}")
    return name


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise MenuInterpretationError(f"{label} must contain exactly {sorted(expected)}")


def _validate_name_en(name_en: Any) -> str:
    if not isinstance(name_en, str) or not name_en.strip():
        raise MenuInterpretationError("candidate nameEn must be a non-empty string")
    if _HANGUL_RE.search(name_en) or not _LATIN_RE.search(name_en):
        raise MenuInterpretationError("candidate nameEn must be English")
    return name_en


def validate_tool_arguments(
    arguments: object,
    restaurant: object,
    raw_source: str,
    source_english: Iterable[str] = (),
) -> MenuInterpretation:
    """Validate parsed tool arguments and assemble canonical mainMenus."""
    restaurant_name = _restaurant_name(restaurant)
    if not isinstance(arguments, Mapping):
        raise MenuInterpretationError("tool arguments must be a JSON object")
    _exact_fields(arguments, {"menuNames", "mainCandidates"}, "tool arguments")

    raw_menu_names = arguments["menuNames"]
    if (
        not isinstance(raw_menu_names, list)
        or not raw_menu_names
        or not all(isinstance(menu, str) and bool(menu.strip()) for menu in raw_menu_names)
    ):
        raise MenuInterpretationError("menuNames must be a non-empty list of strings")
    menu_names = cast(list[str], raw_menu_names)
    if len(menu_names) != len(set(menu_names)):
        raise MenuInterpretationError("menuNames must not contain duplicates")
    for menu_name in menu_names:
        if not _HANGUL_RE.search(menu_name):
            raise MenuInterpretationError("each menuNames item must contain Hangul")
        if _SLOT_LABEL_RE.fullmatch(menu_name.strip()):
            raise MenuInterpretationError("menuNames must not contain meal-slot labels")
        if _BRACKETED_LABEL_RE.fullmatch(menu_name):
            raise MenuInterpretationError("menuNames must not contain bracketed labels")

    raw_candidates = arguments["mainCandidates"]
    if not isinstance(raw_candidates, list):
        raise MenuInterpretationError("mainCandidates must be a list")

    evidence = tuple(source_english)
    if not all(isinstance(item, str) for item in evidence):
        raise MenuInterpretationError("source English evidence must contain only strings")

    indexes: set[int] = set()
    main_menus: list[MainMenu] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, Mapping):
            raise MenuInterpretationError("each candidate must be an object")
        _exact_fields(raw_candidate, {"menuIndex", "nameEn"}, "candidate")

        menu_index = raw_candidate["menuIndex"]
        if isinstance(menu_index, bool) or not isinstance(menu_index, int):
            raise MenuInterpretationError("candidate menuIndex must be an integer")
        if menu_index < 0 or menu_index >= len(menu_names):
            raise MenuInterpretationError("candidate menuIndex is out of range")
        if menu_index in indexes:
            raise MenuInterpretationError("candidate menuIndex values must be unique")
        indexes.add(menu_index)

        name_en = _validate_name_en(raw_candidate["nameEn"])
        if restaurant_name in SITE_ENGLISH_RESTAURANTS and not (
            name_en in raw_source or name_en in evidence
        ):
            raise MenuInterpretationError(
                "site restaurant nameEn must be verbatim source English"
            )
        main_menus.append({"nameKo": menu_names[menu_index], "nameEn": name_en})

    if restaurant_name in SITE_ENGLISH_RESTAURANTS:
        if not main_menus:
            raise MenuInterpretationError(
                "site restaurants require at least one main candidate"
            )
    elif len(main_menus) != min(3, len(menu_names)):
        raise MenuInterpretationError(
            "DORMITORY requires exactly min(3, len(menuNames)) candidates"
        )

    return {"menuNames": menu_names, "mainMenus": main_menus}


def parse_tool_response(
    response: object,
    restaurant: object,
    raw_source: str,
    source_english: Iterable[str] = (),
) -> MenuInterpretation:
    """Validate the chat-completion envelope and its single tool call."""
    try:
        choices = getattr(response, "choices")
        if not isinstance(choices, Sequence) or len(choices) != 1:
            raise MenuInterpretationError("response must contain exactly one choice")
        message = getattr(choices[0], "message")
        tool_calls = getattr(message, "tool_calls")
    except MenuInterpretationError:
        raise
    except (AttributeError, IndexError, TypeError) as error:
        raise MenuInterpretationError("malformed chat-completion response") from error

    if not isinstance(tool_calls, Sequence) or len(tool_calls) != 1:
        raise MenuInterpretationError("response must contain exactly one tool call")
    tool_call = tool_calls[0]
    try:
        function = getattr(tool_call, "function")
        name = getattr(function, "name")
        raw_arguments = getattr(function, "arguments")
    except AttributeError as error:
        raise MenuInterpretationError("malformed tool call") from error
    if name != TOOL_NAME:
        raise MenuInterpretationError(f"unexpected tool call: {name}")
    if not isinstance(raw_arguments, str):
        raise MenuInterpretationError("tool arguments must be JSON text")
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError) as error:
        raise MenuInterpretationError("tool arguments are not valid JSON") from error
    return validate_tool_arguments(
        arguments, restaurant, raw_source, source_english
    )


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
async def _request_completion(
    client: AsyncOpenAI,
    restaurant: str,
    raw_source: str,
    source_english: tuple[str, ...],
) -> object:
    evidence = "\n".join(source_english)
    return await client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Restaurant: {restaurant}\n"
                    f"Source English evidence:\n{evidence}\n\n"
                    f"Raw menu source:\n{raw_source}"
                ),
            },
        ],
        tools=[MENU_TOOL],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        reasoning_effort=cast(Any, "none"),
    )


async def interpret_menu(
    api_key: str,
    restaurant: object,
    raw_source: str,
    source_english: Iterable[str] = (),
) -> MenuInterpretation:
    """Interpret one meal and return menuNames plus canonical mainMenus."""
    restaurant_name = _restaurant_name(restaurant)
    if not isinstance(raw_source, str) or not raw_source.strip():
        raise MenuInterpretationError("raw source must be a non-empty string")
    evidence = tuple(source_english)
    client = AsyncOpenAI(api_key=api_key)
    response = await _request_completion(
        client, restaurant_name, raw_source, evidence
    )
    return parse_tool_response(response, restaurant_name, raw_source, evidence)
