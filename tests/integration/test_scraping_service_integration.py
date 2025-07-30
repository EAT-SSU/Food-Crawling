from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from functions.shared.models.exceptions import HolidayException
from functions.shared.models.model import RestaurantType, RawMenuData, ParsedMenuData, TimeSlot
from functions.shared.services.scraping_service import ScrapingService


# 실제 네트워크 호출을 허용하려면 이 마커를 사용하세요.
# pytest.mark.real_http

@pytest.fixture
def mock_container():
    """Mock DI 컨테이너. 실제 스크래퍼를 사용하고 나머지는 Mock 처리합니다."""
    container = MagicMock()

    # Parser와 API 클라이언트는 Mock 처리
    mock_parser = AsyncMock()
    container.get_parser.return_value = mock_parser

    mock_dev_client = AsyncMock()
    mock_prod_client = AsyncMock()
    container.get_dev_api_client.return_value = mock_dev_client
    container.get_prod_api_client.return_value = mock_prod_client

    # 실제 스크래퍼를 가져오도록 설정
    # 이 부분은 실제 스크래퍼 클래스를 직접 임포트하여 사용합니다.
    from functions.shared.repositories.scrapers.dodam_scraper import DodamScraper
    from functions.shared.repositories.scrapers.haksik_scraper import HaksikScraper
    from functions.shared.repositories.scrapers.faculty_scraper import FacultyScraper
    from functions.shared.repositories.scrapers.dormitory_scraper import DormitoryScraper

    def get_real_scraper(restaurant_type: RestaurantType):
        if restaurant_type == RestaurantType.DODAM:
            return DodamScraper()
        if restaurant_type == RestaurantType.HAKSIK:
            return HaksikScraper()
        if restaurant_type == RestaurantType.FACULTY:
            return FacultyScraper()
        if restaurant_type == RestaurantType.DORMITORY:
            return DormitoryScraper()
        raise ValueError("Unknown restaurant type")

    container.get_scraper.side_effect = get_real_scraper
    return container

@pytest.fixture
def scraping_service(mock_container):
    """테스트용 ScrapingService 인스턴스"""
    return ScrapingService(mock_container)

@pytest.mark.asyncio
async def test_scraping_service_integration_success(scraping_service, mock_container):
    """
    ScrapingService 통합 테스트 (성공 시나리오)
    - 실제 스크래퍼가 데이터를 가져옵니다.
    - Mock 파서가 예상된 형식의 데이터를 반환합니다.
    - Mock API 클라이언트가 올바른 데이터로 호출되는지 확인합니다.
    """
    target_date = "20240325" # 월요일
    restaurant = RestaurantType.DODAM

    # Mock Parser의 반환값 설정
    mock_parsed_menu = ParsedMenuData(
        date=target_date,
        restaurant=restaurant,
        menus={
            "중식1": ["Mocked Menu 1", "Mocked Menu 2"],
            "석식1": ["Mocked Menu 3", "Mocked Menu 4"]
        },
        error_slots={},
        success=True
    )
    mock_container.get_parser.return_value.parse_menu.return_value = mock_parsed_menu

    # Mock API 클라이언트의 반환값 설정
    mock_container.get_dev_api_client.return_value.post_menu.return_value = True
    mock_container.get_prod_api_client.return_value.post_menu.return_value = True

    # Mock MenuPricing과 TimeSlotStrategyFactory
    with patch('functions.shared.services.scraping_service.MenuPricing') as mock_pricing, \
         patch('functions.shared.services.scraping_service.TimeSlotStrategyFactory') as mock_factory:

        mock_pricing.get_price.return_value = 6000
        mock_strategy = MagicMock()
        # `extract_time_slot`이 호출될 때마다 다른 값을 반환하도록 설정
        mock_strategy.extract_time_slot.side_effect = [TimeSlot.LUNCH, TimeSlot.DINNER]
        mock_factory.get_strategy.return_value = mock_strategy

        # 서비스 실행
        result = await scraping_service.scrape_and_process(
            date=target_date,
            restaurant_type=restaurant,
            is_dev=False
        )

        # 검증
        # 1. 스크래퍼가 호출되었는지 확인 (실제 호출되므로 직접 검증은 어려움)
        #    대신, 파서가 RawMenuData와 함께 호출되었는지 확인하여 간접적으로 검증
        mock_container.get_parser.return_value.parse_menu.assert_called_once()
        call_args = mock_container.get_parser.return_value.parse_menu.call_args[0][0]
        assert isinstance(call_args, RawMenuData)
        assert call_args.date == target_date
        assert call_args.restaurant == restaurant

        # 2. API 클라이언트가 올바른 데이터로 호출되었는지 확인
        dev_api_calls = mock_container.get_dev_api_client.return_value.post_menu.call_args_list
        prod_api_calls = mock_container.get_prod_api_client.return_value.post_menu.call_args_list

        assert len(dev_api_calls) == 2
        assert len(prod_api_calls) == 2

        # 중식 호출 검증 (첫 번째 슬롯)
        # post_menu가 positional arguments로 호출되었다고 가정합니다.
        lunch_args = dev_api_calls[0].args
        assert lunch_args[0] == target_date
        assert lunch_args[1] == restaurant
        assert lunch_args[2] == TimeSlot.LUNCH
        assert lunch_args[3] == ["Mocked Menu 1", "Mocked Menu 2"]

        # 석식 호출 검증 (두 번째 슬롯)
        dinner_args = dev_api_calls[1].args
        assert dinner_args[0] == target_date
        assert dinner_args[1] == restaurant
        assert dinner_args[2] == TimeSlot.DINNER
        assert dinner_args[3] == ["Mocked Menu 3", "Mocked Menu 4"]

        # 운영(prod) 클라이언트도 동일한 인자로 호출되었는지 확인합니다.
        assert prod_api_calls[0].args == lunch_args
        assert prod_api_calls[1].args == dinner_args

        # 3. 최종 결과가 파서의 결과와 동일한지 확인
        assert result == mock_parsed_menu

@pytest.mark.asyncio
async def test_scraping_service_integration_holiday(scraping_service, mock_container):
    """
    ScrapingService 통합 테스트 (휴무일 시나리오)
    - 실제 스크래퍼가 휴무일 예외를 발생시킵니다.
    - 파서나 API 클라이언트가 호출되지 않아야 합니다.
    """
    target_date = "20250101" # 신정 (휴무일일 가능성이 높음)
    restaurant = RestaurantType.DODAM

    # 스크래퍼가 HolidayException을 발생시키도록 Mock 처리
    # 실제 네트워크를 호출하는 대신, 예외를 직접 발생시키도록 설정
    mock_scraper = AsyncMock()
    mock_scraper.scrape_menu.side_effect = HolidayException(target_date, "Test Holiday")

    # Fixture에 설정된 side_effect를 None으로 초기화해야 return_value가 적용됩니다.
    mock_container.get_scraper.side_effect = None
    mock_container.get_scraper.return_value = mock_scraper

    # 서비스 실행 및 예외 검증
    with pytest.raises(HolidayException):
        await scraping_service.scrape_and_process(
            date=target_date,
            restaurant_type=restaurant
        )

    # 파서와 API 클라이언트가 호출되지 않았는지 확인
    mock_container.get_parser.return_value.parse_menu.assert_not_called()
    mock_container.get_dev_api_client.return_value.post_menu.assert_not_called()
    mock_container.get_prod_api_client.return_value.post_menu.assert_not_called()