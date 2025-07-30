import asyncio
import logging
from typing import Optional, List

from functions.shared.models.exceptions import MenuPostException
from functions.shared.models.model import RestaurantType, TimeSlot, MenuPricing, ParsedMenuData, RawMenuData
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient
from functions.shared.services.time_slot_strategy import TimeSlotStrategyFactory

logger = logging.getLogger(__name__)


class ScrapingService:
    """메뉴 스크래핑 서비스 - 개선된 책임 분리 버전"""

    def __init__(self, parser, prod_api_client, dev_api_client, scraper_factory):
        self._parser = parser
        self._prod_api_client = prod_api_client
        self._dev_api_client = dev_api_client
        self._scraper_factory = scraper_factory

    async def scrape_and_process(self, date: str, restaurant_type: RestaurantType,
                                 is_dev: bool = True) -> ParsedMenuData:
        """메뉴 스크래핑부터 API 전송까지 전체 프로세스"""
        logger.info(f"메뉴 처리 시작: {restaurant_type.korean_name} {date}, 개발모드: {is_dev}")

        # 1. 스크래핑 단계 (HTML 추출 + GPT 파싱)
        parsed_menu = await self.scrape_menu(date, restaurant_type)

        # 2. API 전송 단계
        await self.send_to_api(parsed_menu, is_dev)

        return parsed_menu

    async def scrape_and_process_dormitory(self, date: str, is_dev: bool = True) -> List[ParsedMenuData]:
        """기숙사식당 전용 메뉴 스크래핑부터 API 전송까지 전체 프로세스"""
        logger.info(f"기숙사식당 주간 메뉴 처리 시작: {date}, 개발모드: {is_dev}")

        # 1. 스크래핑 단계 (주간)
        parsed_menus = await self.scrape_dormitory_weekly(date)

        # 2. API 전송 단계 (각 날짜별)
        for parsed_menu in parsed_menus:
            await self.send_to_api(parsed_menu, is_dev)

        logger.info(f"기숙사식당 주간 메뉴 처리 완료: {len(parsed_menus)}일치")
        return parsed_menus

    async def scrape_menu(self, date: str, restaurant_type: RestaurantType) -> ParsedMenuData:
        """
        메뉴 스크래핑: HTML 추출 + GPT 파싱까지 완료
        (테스트하기 쉬운 완전한 단위)
        """
        logger.info(f"스크래핑 시작: {restaurant_type.korean_name} {date}")

        # 1. HTML 추출
        raw_menu = await self._extract_raw_menu(date, restaurant_type)  # HolidayException or Sraping 실패
        logger.info(f"HTML 추출 완료: {restaurant_type.korean_name} {date}")

        # 2. GPT 파싱
        parsed_menu = await self._parse_menu(raw_menu)
        logger.info(f"GPT 파싱 완료: {restaurant_type.korean_name} {date}")

        # 3. 결과 로깅
        self._log_scraping_result(parsed_menu)

        logger.info(f"스크래핑 완료: {restaurant_type.korean_name} {date}")
        return parsed_menu

    async def scrape_dormitory_weekly(self, date: str) -> List[ParsedMenuData]:
        """
        기숙사 주간 스크래핑: HTML 추출 + GPT 파싱까지 완료
        (테스트하기 쉬운 완전한 단위)
        """
        logger.info(f"기숙사 주간 스크래핑 시작: {date}")

        # 1. HTML 추출 (주간)
        raw_menus = await self._extract_dormitory_weekly(date)
        logger.info(f"기숙사 주간 HTML 추출 완료: {len(raw_menus)}일치")

        # 2. GPT 파싱 (각 날짜별)
        parsed_menus = []
        for raw_menu in raw_menus:
            parsed_menu = await self._parse_menu(raw_menu)
            parsed_menus.append(parsed_menu)
            self._log_scraping_result(parsed_menu)

        logger.info(f"기숙사 주간 스크래핑 완료: {len(parsed_menus)}일치")
        return parsed_menus

    async def send_to_api(self, parsed_menu: ParsedMenuData, is_dev: bool = True) -> None:
        """
        파싱된 메뉴를 API에 전송하고 결과를 ParsedMenuData에 반영
        """
        logger.info(f"API 전송 시작: {parsed_menu.restaurant.korean_name} {parsed_menu.date}")

        clients: List[SpringAPIClient] = [self._dev_api_client]
        if not is_dev:  # 운영 환경
            clients.append(self._prod_api_client)

        restaurant, date = parsed_menu.restaurant, parsed_menu.date
        sent_count = 0
        failed_slots = []

        for slot, menu in parsed_menu.get_successful_slots().items():
            try:
                # 시간대와 가격 확인
                time_slot = self._extract_time_slot(slot, restaurant)
                if not time_slot:
                    continue

                price = MenuPricing.get_price(restaurant, time_slot)
                if not price:
                    continue

                menu_items = parsed_menu.menus[slot]

                await asyncio.gather(*[
                    client.post_menu(date, restaurant, time_slot, menu_items, price)
                    for client in clients
                ])
                sent_count += 1
                logger.info(
                    f"API 전송 성공: {restaurant.english_name} "
                    f"{time_slot.english_name} ({len(menu_items)}개 메뉴)"
                )
            except MenuPostException as e:
                error_msg = f"API 전송 부분 실패: {restaurant.korean_name} {slot.english_name} - {e}"
                logger.error(error_msg)

                # API 전송 실패를 ParsedMenuData에 기록
                parsed_menu.error_slots[slot] = e
                failed_slots.append(slot)
                continue

        # 전체 성공 여부 업데이트
        if failed_slots:
            parsed_menu.success = False
            logger.warning(f"API 전송 부분 실패: {failed_slots}")

        # API 전송이 모두 실패했다면 예외 발생
        if sent_count == 0 and len(parsed_menu.get_successful_slots()) > 0:
            raise MenuPostException(
                target_date=parsed_menu.date,
                restaurant_type=restaurant,
                details=f"모든 API 전송 실패: {len(failed_slots)}개 슬롯 {parsed_menu.error_slots}"
            )

        logger.info(
            f"API 전송 완료: {restaurant.korean_name} {date} - "
            f"{sent_count}개 슬롯 전송 성공, {len(failed_slots)}개 슬롯 실패"
        )

    # === 내부 구현 메서드들 ===

    async def _extract_raw_menu(self, date: str, restaurant_type: RestaurantType) -> RawMenuData:
        """HTML 추출만 담당 (순수 웹 스크래핑)"""
        scraper = self._scraper_factory(restaurant_type)
        return await scraper.scrape_menu(date)

    async def _extract_dormitory_weekly(self, date: str) -> List[RawMenuData]:
        """기숙사 주간 HTML 추출만 담당"""
        scraper = self._scraper_factory(RestaurantType.DORMITORY)
        return await scraper.scrape_menu(date)  # List[RawMenuData] 반환

    async def _parse_menu(self, raw_menu: RawMenuData) -> ParsedMenuData:
        """GPT 파싱만 담당 (순수 파싱)"""
        return await self._parser.parse_menu(raw_menu)

    def _log_scraping_result(self, parsed_menu: ParsedMenuData) -> None:
        """스크래핑 결과 로깅"""
        total_slots = len(parsed_menu.get_all_slots())
        success_slots = len(parsed_menu.get_successful_slots())

        restaurant = parsed_menu.restaurant.korean_name
        date = parsed_menu.date

        if parsed_menu.error_slots:
            failed_slots = list(parsed_menu.error_slots.keys())
            logger.warning(f"부분 스크래핑 완료: {restaurant} {date} - 성공: {success_slots}/{total_slots}, 실패: {failed_slots}")
        else:
            logger.info(f"전체 스크래핑 완료: {restaurant} {date} - {success_slots}/{total_slots} 슬롯 성공")

    def _extract_time_slot(self, menu_slot: str, restaurant: RestaurantType) -> Optional[TimeSlot]:
        """메뉴 슬롯에서 시간대를 추출합니다. (Strategy Pattern 사용)"""
        try:
            strategy = TimeSlotStrategyFactory.get_strategy(restaurant)
            return strategy.extract_time_slot(menu_slot)
        except ValueError as e:
            logger.error(f"지원하지 않는 식당 타입: {e}")
            return None
