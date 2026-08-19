from functions.clients import format_slack_text


SENTINEL = "<html>SECRET_TOKEN https://provider.invalid/token Cause Critical"


def test_final_failure_slack_uses_only_allowlisted_error_text():
    text = format_slack_text(
        {
            "type": "final_failure",
            "date": "20260713",
            "restaurant": "기숙사식당",
            "error_type": SENTINEL,
            "Cause": SENTINEL,
        }
    )
    assert text == "🍽️ 기숙사식당 (20260713)\n⚠️ 최종 처리 실패: 알 수 없는 처리 오류"
    assert SENTINEL not in text
    assert "provider.invalid" not in text


def test_production_like_partial_failure_uses_only_allowlisted_slot_reason():
    text = format_slack_text(
        {
            "type": "date_summary",
            "date": "20260713",
            "restaurant": "도담식당",
            "menus": {
                "중식1": ["제육볶음", "쌀밥"],
                "중식4": [SENTINEL],
            },
            "warnings": [
                {
                    "slot": "중식4",
                    "stage": "notification",
                    "reason": SENTINEL,
                    "error_type": SENTINEL,
                }
            ],
            "errors": [
                {
                    "slot": "중식4",
                    "stage": "menu_ai",
                    "error_type": SENTINEL,
                    "Cause": SENTINEL,
                }
            ],
        }
    )
    assert text == (
        "🍽️ 도담식당 (20260713)\n"
        "• 중식1: 제육볶음, 쌀밥\n"
        "⚠️ 중식4: 메뉴 파싱 실패"
    )
    for unsafe in ("<html>", "SECRET_TOKEN", "https://", "provider.invalid", "Cause", "Critical"):
        assert unsafe not in text


def test_whole_day_holiday_has_exactly_one_status_without_empty_menu_line():
    text = format_slack_text(
        {
            "type": "date_summary",
            "date": "20260812",
            "restaurant": "학생식당",
            "menus": {"전체": []},
            "empty_reasons": {"전체": "HOLIDAY"},
            "warnings": [{"reason": SENTINEL}],
            "errors": [],
        }
    )

    assert text == "🍽️ 학생식당 (20260812)\nℹ️ 휴무일"
    assert "메뉴 없음" not in text


def test_empty_slot_and_all_failure_stages_use_concise_allowlisted_labels():
    text = format_slack_text(
        {
            "type": "date_summary",
            "date": "20260812",
            "restaurant": "도담식당",
            "menus": {"중식1": [], "중식2": [], "중식3": [], "중식4": []},
            "empty_reasons": {
                "중식1": "CLOSED_MARKER",
                "중식2": "SOURCE_EMPTY",
            },
            "errors": [
                {"slot": "중식3", "stage": "source", "error_type": SENTINEL},
            ],
            "warnings": [
                {"slot": "중식4", "stage": "publication", "reason": SENTINEL},
                {"slot": "중식4", "stage": "publication", "reason": SENTINEL},
                {"slot": "중식5", "stage": "unmatched", "items": [SENTINEL]},
            ],
        }
    )

    assert text == (
        "🍽️ 도담식당 (20260812)\n"
        "ℹ️ 중식1: 미운영\n"
        "ℹ️ 중식2: 메뉴 미게시 또는 원본 누락\n"
        "⚠️ 중식3: 메뉴 원본 확인 필요\n"
        "⚠️ 중식4: 메뉴 저장 실패\n"
        "⚠️ 중식5: 대표메뉴 매칭 실패"
    )
    assert SENTINEL not in text
