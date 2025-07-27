import pytest

from functions.shared.models.exceptions import (
    HolidayException, MenuFetchException, MenuParseException, WeirdRestaurantName
)
from functions.shared.models.model import (
    RestaurantType, TimeSlot, MenuPricing, RawMenuData,
    ParsedMenuData, ResponseBuilder
)


class TestRestaurantType:
    """RestaurantType Enum 테스트"""

    def test_restaurant_type_properties(self):
        """식당 타입의 속성들이 올바른지 테스트"""
        assert RestaurantType.HAKSIK.korean_name == "학생식당"
        assert RestaurantType.HAKSIK.english_name == "HAKSIK"
        assert RestaurantType.HAKSIK.soongguri_rcd == 1

        assert RestaurantType.DODAM.korean_name == "도담식당"
        assert RestaurantType.DODAM.soongguri_rcd == 2

        assert RestaurantType.FACULTY.korean_name == "교직원식당"
        assert RestaurantType.FACULTY.soongguri_rcd == 7

        assert RestaurantType.DORMITORY.korean_name == "기숙사식당"
        assert RestaurantType.DORMITORY.soongguri_rcd is None


class TestTimeSlot:
    """TimeSlot Enum 테스트"""

    def test_time_slot_properties(self):
        """시간대 속성들이 올바른지 테스트"""
        assert TimeSlot.ONE_DOLLAR_MORNING.korean_name == "1000원 조식"
        assert TimeSlot.LUNCH.korean_name == "점심"
        assert TimeSlot.DINNER.korean_name == "저녁"

    def test_time_slot_parse(self):
        """시간대 파싱이 올바른지 테스트"""
        assert TimeSlot.parse("점심") == TimeSlot.LUNCH
        assert TimeSlot.parse("L") == TimeSlot.LUNCH
        assert TimeSlot.parse("LUNCH") == TimeSlot.LUNCH

        with pytest.raises(ValueError):
            TimeSlot.parse("알 수 없는 시간대")


class TestMenuPricing:
    """MenuPricing 클래스 테스트"""

    def test_get_price(self):
        """가격 조회가 올바른지 테스트"""
        assert MenuPricing.get_price(RestaurantType.DODAM, TimeSlot.LUNCH) == 6000
        assert MenuPricing.get_price(RestaurantType.HAKSIK, TimeSlot.ONE_DOLLAR_MORNING) == 1000
        assert MenuPricing.get_price(RestaurantType.FACULTY, TimeSlot.LUNCH) == 7000

        # 존재하지 않는 조합
        assert MenuPricing.get_price(RestaurantType.FACULTY, TimeSlot.DINNER) is None

    def test_get_available_times(self):
        """이용 가능한 시간대 조회 테스트"""
        haksik_times = MenuPricing.get_available_times(RestaurantType.HAKSIK)
        assert TimeSlot.ONE_DOLLAR_MORNING in haksik_times
        assert TimeSlot.LUNCH in haksik_times

        faculty_times = MenuPricing.get_available_times(RestaurantType.FACULTY)
        assert TimeSlot.LUNCH in faculty_times
        assert TimeSlot.DINNER not in faculty_times


class TestRawMenuData:
    """RawMenuData 데이터클래스 테스트"""

    def test_raw_menu_data_creation(self):
        """RawMenuData 생성 테스트"""
        menu_texts = {"중식1": "김치찌개 밥", "석식1": "불고기 밥"}
        raw_data = RawMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menu_texts=menu_texts
        )

        assert raw_data.date == "20240325"
        assert raw_data.restaurant == RestaurantType.DODAM
        assert raw_data.menu_texts == menu_texts


class TestParsedMenuData:
    """ParsedMenuData 데이터클래스 테스트"""

    @pytest.fixture
    def sample_parsed_menu(self):
        """테스트용 샘플 ParsedMenuData"""
        return ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={
                "중식1": ["김치찌개", "밥", "김치"],
                "석식1": ["불고기", "밥", "된장국"],
                "중식2": []  # 빈 메뉴
            },
            error_slots={"중식3": "파싱 실패"},
            success=False
        )

    def test_get_successful_slots(self, sample_parsed_menu):
        """성공한 슬롯 조회 테스트"""
        successful = sample_parsed_menu.get_successful_slots()
        assert "중식1" in successful
        assert "석식1" in successful
        assert "중식2" not in successful  # 빈 메뉴
        assert "중식3" not in successful  # 에러 슬롯

    def test_get_all_slots(self, sample_parsed_menu):
        """전체 슬롯 조회 테스트"""
        all_slots = sample_parsed_menu.get_all_slots()
        assert len(all_slots) == 3
        assert "중식1" in all_slots
        assert "석식1" in all_slots
        assert "중식2" in all_slots

    def test_is_complete_success(self, sample_parsed_menu):
        """완전 성공 여부 테스트"""
        assert not sample_parsed_menu.is_complete_success()

        # 완전 성공 케이스
        success_menu = ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"]},
            error_slots={},
            success=True
        )
        assert success_menu.is_complete_success()

    def test_is_partial_success(self, sample_parsed_menu):
        """부분 성공 여부 테스트"""
        assert sample_parsed_menu.is_partial_success()


class TestResponseBuilder:
    """ResponseBuilder 클래스 테스트"""

    @pytest.fixture
    def sample_parsed_menu(self):
        """테스트용 샘플 ParsedMenuData"""
        return ParsedMenuData(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            menus={"중식1": ["김치찌개", "밥"]},
            error_slots={},
            success=True
        )

    def test_create_success_response(self, sample_parsed_menu):
        """성공 응답 생성 테스트"""
        response = ResponseBuilder.create_success_response(
            sample_parsed_menu,
            message="테스트 메시지"
        )

        assert response['statusCode'] == 200
        assert 'application/json' in response['headers']['Content-Type']

        import json
        body = json.loads(response['body'])
        assert body['success'] is True
        assert body['date'] == "20240325"
        assert body['restaurant'] == "도담식당"
        assert body['message'] == "테스트 메시지"

    def test_create_error_response(self):
        """에러 응답 생성 테스트"""
        error = Exception("테스트 에러")
        response = ResponseBuilder.create_error_response(
            date="20240325",
            restaurant=RestaurantType.DODAM,
            error=error,
            status_code=500
        )

        assert response['statusCode'] == 500

        import json
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error'] == "테스트 에러"
        assert body['error_type'] == "Exception"


class TestCustomExceptions:
    """커스텀 예외들 테스트"""

    def test_holiday_exception(self):
        """HolidayException 테스트"""
        exc = HolidayException("20240325", "휴무일 데이터")
        assert exc.target_date == "20240325"
        assert exc.raw_data == "휴무일 데이터"
        assert "휴무일" in str(exc)

    def test_menu_fetch_exception(self):
        """MenuFetchException 테스트"""
        exc = MenuFetchException("20240325", "fetch 실패 데이터")
        assert exc.target_date == "20240325"
        assert exc.raw_data == "fetch 실패 데이터"

    def test_menu_parse_exception(self):
        """MenuParseException 테스트"""
        exc = MenuParseException("20240325", "파싱 실패 상세")
        assert exc.target_date == "20240325"
        assert exc.details == "파싱 실패 상세"

    def test_weird_restaurant_name(self):
        """WeirdRestaurantName 테스트"""
        exc = WeirdRestaurantName("20240325", "도담식당", "조식")
        assert exc.target_date == "20240325"
        assert exc.restrant_name == "도담식당"
