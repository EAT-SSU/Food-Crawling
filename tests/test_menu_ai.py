import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import wait_none

from functions import menu_ai


def _response(arguments, *, name=menu_ai.TOOL_NAME, call_count=1):
    calls = [
        SimpleNamespace(
            function=SimpleNamespace(
                name=name,
                arguments=(
                    arguments
                    if isinstance(arguments, str)
                    else json.dumps(arguments, ensure_ascii=False)
                ),
            )
        )
        for _ in range(call_count)
    ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=calls))]
    )


def _valid_dormitory():
    return {
        "menuNames": ["김치찌개", "쌀밥", "계란말이"],
        "mainCandidates": [
            {"menuIndex": 0, "nameEn": "Kimchi Stew"},
            {"menuIndex": 1, "nameEn": "Rice"},
            {"menuIndex": 2, "nameEn": "Rolled Omelette"},
        ],
    }


def test_tool_schema_is_strict_and_index_based():
    function_schema = cast(dict[str, Any], cast(object, menu_ai.MENU_TOOL["function"]))
    assert menu_ai.MODEL_ID == "gpt-5.6-luna"
    assert function_schema["name"] == "extract_main_menus"
    assert function_schema["strict"] is True
    parameters = function_schema["parameters"]
    assert parameters["additionalProperties"] is False
    assert parameters["required"] == ["menuNames", "mainCandidates"]
    candidate = parameters["properties"]["mainCandidates"]["items"]
    assert candidate["additionalProperties"] is False
    assert candidate["required"] == ["menuIndex", "nameEn"]


def test_dormitory_assembles_name_ko_directly_from_menu_index():
    arguments = _valid_dormitory()
    result = menu_ai.parse_tool_response(
        _response(arguments), "DORMITORY", "김치찌개 쌀밥 계란말이"
    )

    assert result == {
        "menuNames": ["김치찌개", "쌀밥", "계란말이"],
        "mainMenus": [
            {"nameKo": "김치찌개", "nameEn": "Kimchi Stew"},
            {"nameKo": "쌀밥", "nameEn": "Rice"},
            {"nameKo": "계란말이", "nameEn": "Rolled Omelette"},
        ],
    }
    assert result["mainMenus"][1]["nameKo"] is result["menuNames"][1]


def test_duplicate_menu_text_is_preserved_when_indexes_are_unique():
    arguments = {
        "menuNames": ["쌀밥", "쌀밥"],
        "mainCandidates": [
            {"menuIndex": 0, "nameEn": "Steamed Rice"},
            {"menuIndex": 1, "nameEn": "Rice"},
        ],
    }

    result = menu_ai.validate_tool_arguments(
        arguments, "DORMITORY", "쌀밥 쌀밥"
    )

    assert result["menuNames"] == ["쌀밥", "쌀밥"]
    assert [item["nameKo"] for item in result["mainMenus"]] == ["쌀밥", "쌀밥"]


@pytest.mark.parametrize("restaurant", ["HAKSIK", "DODAM", "FACULTY"])
def test_site_restaurants_accept_only_verbatim_source_english(restaurant):
    arguments = {
        "menuNames": ["제육볶음"],
        "mainCandidates": [{"menuIndex": 0, "nameEn": "Spicy Pork"}],
    }

    from_raw = menu_ai.validate_tool_arguments(
        arguments, restaurant, "중식1 제육볶음 Spicy Pork 쌀밥"
    )
    from_evidence = menu_ai.validate_tool_arguments(
        arguments, restaurant, "중식1 제육볶음", ["Spicy Pork"]
    )

    assert from_raw["mainMenus"] == [
        {"nameKo": "제육볶음", "nameEn": "Spicy Pork"}
    ]
    assert from_evidence == from_raw


def test_site_restaurant_rejects_generated_or_altered_english():
    arguments = {
        "menuNames": ["제육볶음"],
        "mainCandidates": [{"menuIndex": 0, "nameEn": "Spicy Pork Dish"}],
    }

    with pytest.raises(menu_ai.MenuInterpretationError, match="verbatim"):
        menu_ai.validate_tool_arguments(
            arguments, "DODAM", "제육볶음 Spicy Pork", ["Spicy Pork"]
        )


@pytest.mark.parametrize(
    ("menu_names", "candidates"),
    [
        (["카레라이스"], [{"menuIndex": 0, "nameEn": "Curry Rice"}]),
        (
            ["카레라이스", "단무지"],
            [
                {"menuIndex": 0, "nameEn": "Curry Rice"},
                {"menuIndex": 1, "nameEn": "Pickled Radish"},
            ],
        ),
    ],
)
def test_dormitory_requires_all_candidates_when_fewer_than_three(
    menu_names, candidates
):
    result = menu_ai.validate_tool_arguments(
        {"menuNames": menu_names, "mainCandidates": candidates},
        "DORMITORY",
        "원본에는 영어가 없어도 됨",
    )

    assert len(result["mainMenus"]) == len(menu_names)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        {"menuNames": ["밥"], "mainCandidates": [], "extra": 1},
        {"mainCandidates": []},
        {"menuNames": ["밥"]},
        {"menuNames": [], "mainCandidates": []},
        {"menuNames": [1], "mainCandidates": []},
        {"menuNames": [" "], "mainCandidates": []},
        {"menuNames": ["밥"], "mainCandidates": "bad"},
        {"menuNames": ["밥"], "mainCandidates": ["bad"]},
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 0, "nameEn": "Rice", "extra": 1}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 0}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"nameEn": "Rice"}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": -1, "nameEn": "Rice"}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 1, "nameEn": "Rice"}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": True, "nameEn": "Rice"}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 0.0, "nameEn": "Rice"}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 0, "nameEn": " "}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 0, "nameEn": "쌀밥"}],
        },
        {
            "menuNames": ["밥"],
            "mainCandidates": [{"menuIndex": 0, "nameEn": "123"}],
        },
        {
            "menuNames": ["밥", "국"],
            "mainCandidates": [
                {"menuIndex": 0, "nameEn": "Rice"},
                {"menuIndex": 0, "nameEn": "Rice"},
            ],
        },
    ],
)
def test_malformed_argument_shapes_fail_deterministically(arguments):
    with pytest.raises(menu_ai.MenuInterpretationError):
        menu_ai.validate_tool_arguments(arguments, "DORMITORY", "밥 국")


@pytest.mark.parametrize(
    "arguments",
    [
        {"menuNames": ["밥"], "mainCandidates": []},
        {
            "menuNames": ["밥", "국", "김치", "계란"],
            "mainCandidates": [
                {"menuIndex": 0, "nameEn": "Rice"},
                {"menuIndex": 1, "nameEn": "Soup"},
            ],
        },
        {
            "menuNames": ["밥", "국", "김치"],
            "mainCandidates": [
                {"menuIndex": 0, "nameEn": "Rice"},
                {"menuIndex": 1, "nameEn": "Soup"},
                {"menuIndex": 2, "nameEn": "Kimchi"},
                {"menuIndex": 0, "nameEn": "Rice"},
            ],
        },
    ],
)
def test_dormitory_candidate_count_policy_is_strict(arguments):
    with pytest.raises(menu_ai.MenuInterpretationError):
        menu_ai.validate_tool_arguments(arguments, "DORMITORY", "밥 국 김치 계란")


def test_site_restaurants_require_at_least_one_candidate():
    with pytest.raises(menu_ai.MenuInterpretationError, match="at least one"):
        menu_ai.validate_tool_arguments(
            {"menuNames": ["밥"], "mainCandidates": []},
            "HAKSIK",
            "밥 Rice",
        )


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))]),
        _response({}, name="wrong_tool"),
        _response({}, call_count=2),
        _response("{"),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
    ],
)
def test_invalid_tool_envelopes_are_rejected(response):
    with pytest.raises(menu_ai.MenuInterpretationError):
        menu_ai.parse_tool_response(response, "DORMITORY", "밥")


@pytest.mark.asyncio
async def test_interpret_menu_uses_exact_model_tool_and_choice():
    completion = AsyncMock(return_value=_response(_valid_dormitory()))
    client = MagicMock()
    client.chat.completions.create = completion

    with patch("functions.menu_ai.AsyncOpenAI", return_value=client) as constructor:
        result = await menu_ai.interpret_menu(
            "secret", "DORMITORY", "김치찌개 쌀밥 계란말이"
        )

    constructor.assert_called_once_with(api_key="secret")
    assert completion.await_args is not None
    kwargs = completion.await_args.kwargs
    assert kwargs["model"] == "gpt-5.6-luna"
    assert kwargs["tools"] == [menu_ai.MENU_TOOL]
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": menu_ai.TOOL_NAME},
    }
    assert result["mainMenus"][1] == {"nameKo": "쌀밥", "nameEn": "Rice"}


@pytest.mark.asyncio
async def test_transient_provider_failure_retries_three_times_without_test_sleep():
    completion = AsyncMock(side_effect=RuntimeError("transient"))
    client = MagicMock()
    client.chat.completions.create = completion
    request_completion = cast(Any, menu_ai._request_completion)
    original_wait = request_completion.retry.wait
    request_completion.retry.wait = wait_none()
    try:
        with patch("functions.menu_ai.AsyncOpenAI", return_value=client):
            with pytest.raises(RuntimeError, match="transient"):
                await menu_ai.interpret_menu("secret", "DORMITORY", "밥")
    finally:
        request_completion.retry.wait = original_wait

    assert completion.await_count == 3
    assert request_completion.retry.stop.max_attempt_number == 3
    assert original_wait.wait_fixed == 5


@pytest.mark.asyncio
async def test_malformed_completion_is_not_retried():
    completion = AsyncMock(return_value=_response("{"))
    client = MagicMock()
    client.chat.completions.create = completion

    with patch("functions.menu_ai.AsyncOpenAI", return_value=client):
        with pytest.raises(menu_ai.MenuInterpretationError, match="valid JSON"):
            await menu_ai.interpret_menu("secret", "DORMITORY", "밥")

    completion.assert_awaited_once()
