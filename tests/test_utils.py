from datetime import datetime
from unittest.mock import patch

from functions.shared.utils.date_utils import get_next_weekdays, get_current_weekdays
from functions.shared.utils.parsing_utils import (
    parse_table_to_dict, strip_string_from_html
)


class TestDateUtils:
    """날짜 유틸리티 함수들 테스트"""

    @patch('functions.shared.utils.date_utils.datetime')
    def test_get_next_weekdays(self, mock_datetime):
        """다음 주 평일 조회 테스트"""
        # 2024년 3월 25일 월요일로 고정
        mock_datetime.now.return_value = datetime(2024, 3, 25, 10, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        weekdays = get_next_weekdays()

        assert len(weekdays) == 5
        assert all(isinstance(day, str) for day in weekdays)
        assert weekdays[0].endswith("01")  # 다음 주 월요일

    @patch('functions.shared.utils.date_utils.datetime')
    def test_get_current_weekdays(self, mock_datetime):
        """현재 주 평일 조회 테스트"""
        # 2024년 3월 27일 수요일로 고정
        mock_datetime.now.return_value = datetime(2024, 3, 27, 10, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        weekdays = get_current_weekdays()

        assert len(weekdays) == 5
        assert weekdays[0] == "20240325"  # 그 주 월요일
        assert weekdays[4] == "20240329"  # 그 주 금요일


class TestParsingUtils:
    """파싱 유틸리티 함수들 테스트"""

    def test_strip_string_from_html(self):
        """HTML 텍스트 정리 테스트"""

        # Mock BeautifulSoup 객체들
        class MockElement:
            def __init__(self, text):
                self.stripped_strings = text.split()

        menu_dict = {
            "중식1": MockElement("김치찌개 밥 김치"),
            "석식1": MockElement("불고기 밥 된장국")
        }

        result = strip_string_from_html(menu_dict)

        assert result["중식1"] == "김치찌개 밥 김치"
        assert result["석식1"] == "불고기 밥 된장국"

    def test_parse_table_to_dict_with_sample_html(self):
        """실제 HTML 구조로 테이블 파싱 테스트"""
        html_content = """
        <table>
            <tr>
                <td class="menu_nm">중식1</td>
                <td>김치찌개, 밥, 김치</td>
            </tr>
            <tr>
                <td class="menu_nm">석식1</td>
                <td>불고기, 밥, 된장국</td>
            </tr>
        </table>
        """

        result = parse_table_to_dict(html_content)

        assert "중식1" in result
        assert "석식1" in result
        assert len(result) == 2
