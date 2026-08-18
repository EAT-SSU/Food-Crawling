from functions.clients import format_slack_text


SENTINEL = "<html>SECRET_TOKEN https://provider.invalid/token"


def test_final_failure_slack_uses_only_allowlisted_error_text():
    text = format_slack_text(
        {
            "type": "final_failure",
            "date": "20260713",
            "restaurant": "DORMITORY",
            "error_type": SENTINEL,
            "Cause": SENTINEL,
        }
    )
    assert text == "[DORMITORY] 20260713 최종 처리 실패: 알 수 없는 처리 오류"
    assert SENTINEL not in text
    assert "provider.invalid" not in text


def test_date_summary_omits_raw_warning_and_error_payloads():
    text = format_slack_text(
        {
            "type": "date_summary",
            "date": "20260713",
            "restaurant": "DODAM",
            "menus": {"중식1": ["제육볶음"]},
            "warnings": [{"provider": SENTINEL}],
            "errors": [{"traceback": SENTINEL}],
        }
    )
    assert "제육볶음" in text
    assert "경고: 1건" in text
    assert "오류: 1건" in text
    assert SENTINEL not in text
