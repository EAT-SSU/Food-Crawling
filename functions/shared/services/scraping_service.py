import asyncio
import logging
from typing import Optional, List

from functions.config.dependencies import DependencyContainer
from functions.shared.models.model import RestaurantType, TimeSlot, MenuPricing, ParsedMenuData
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient
from functions.shared.services.time_slot_strategy import TimeSlotStrategyFactory

logger = logging.getLogger(__name__)


class ScrapingService:
    """메뉴 스크래핑 서비스 - ResponseBuilder 적용"""

    def __init__(self, container):
        self._container: DependencyContainer = container

    async def scrape_and_process(self, date: str, restaurant_type: RestaurantType,
                                 is_dev: bool = True) -> ParsedMenuData:
        """메뉴 스크래핑부터 API 전송까지 전체 프로세스를 처리합니다."""
        logger.info(f"메뉴 처리 시작: {restaurant_type.korean_name} {date}, 개발모드: {is_dev}")

        # 1. 의존성 주입
        scraper = self._container.get_scraper(restaurant_type)
        parser = self._container.get_parser()

        # 2. 스크래핑
        raw_menu = await scraper.scrape_menu(date)
        logger.info(f"스크래핑 완료: {restaurant_type.korean_name} {date}")

        # 3. GPT 파싱
        parsed_menu = await parser.parse_menu(raw_menu)
        logger.info(f"파싱 완료: {restaurant_type.korean_name} {date}")

        # 4. API 전송 (성공한 것만)
        await self._send_menus_to_api(parsed_menu, is_dev)

        # 5. 부분 실패 로깅
        self._log_processing_result(parsed_menu)

        return parsed_menu

    async def scrape_and_process_dormitory(self, date: str, is_dev: bool = True) -> List[ParsedMenuData]:
        """기숙사식당 전용 메뉴 스크래핑 (주간 처리)"""
        logger.info(f"기숙사식당 주간 메뉴 처리 시작: {date}, 개발모드: {is_dev}")

        # 1. 의존성 주입
        scraper = self._container.get_scraper(RestaurantType.DORMITORY)
        parser = self._container.get_parser()

        # 2. 스크래핑 (List[RawMenuData] 반환)
        raw_menus = await scraper.scrape_menu(date)
        logger.info(f"기숙사 스크래핑 완료: {len(raw_menus)}일치 메뉴")

        # 3. 각 RawMenuData를 GPT로 파싱
        parsed_menus = []
        for raw_menu in raw_menus:
            logger.info(f"GPT 파싱 시작: {raw_menu.date}")

            parsed_menu = await parser.parse_menu(raw_menu)
            logger.info(f"GPT 파싱 완료: {raw_menu.date}")

            # 4. API 전송
            await self._send_menus_to_api(parsed_menu, is_dev)

            # 5. 결과 로깅
            self._log_processing_result(parsed_menu)

            parsed_menus.append(parsed_menu)

        logger.info(f"기숙사식당 주간 메뉴 처리 완료: {len(parsed_menus)}일치")
        return parsed_menus

    async def _send_menus_to_api(self, parsed_menu: ParsedMenuData, is_dev: bool) -> None:
        """파싱된 메뉴를 API에 전송합니다. (성공한 것만)"""
        clients: List[SpringAPIClient] = [self._container.get_dev_api_client()]
        if not is_dev:  # 운영 환경
            clients.append(self._container.get_prod_api_client())

        restaurant, date = parsed_menu.restaurant, parsed_menu.date
        sent_count = 0

        for slot in parsed_menu.get_successful_slots():
            # 시간대와 가격 확인
            time_slot = self._extract_time_slot(slot, restaurant)
            if not time_slot:
                continue

            price = MenuPricing.get_price(restaurant, time_slot)
            if not price:
                continue

            menu_items = parsed_menu.menus[slot]

            try:
                await asyncio.gather(*[
                    client.post_menu(date, restaurant, time_slot, menu_items, price)
                    for client in clients
                ])
                sent_count += 1
                logger.info(
                    f"API 전송 성공: {restaurant.english_name} "
                    f"{time_slot.english_name} ({len(menu_items)}개 메뉴)"
                )
            except Exception as e:
                logger.error(
                    f"API 전송 실패: {restaurant.english_name} "
                    f"{time_slot.english_name} - {e}"
                )

        logger.info(
            f"API 전송 완료: {restaurant.korean_name} {date} - "
            f"{sent_count}개 슬롯 전송됨"
        )

    def _log_processing_result(self, parsed_menu: ParsedMenuData) -> None:
        """처리 결과 간단 로깅"""
        total_slots = len(parsed_menu.get_all_slots())
        success_slots = len(parsed_menu.get_successful_slots())

        restaurant = parsed_menu.restaurant.korean_name
        date = parsed_menu.date

        if parsed_menu.error_slots:
            failed_slots = list(parsed_menu.error_slots.keys())
            logger.warning(f"부분 처리 완료: {restaurant} {date} - 성공: {success_slots}/{total_slots}, 실패: {failed_slots}")
        else:
            logger.info(f"전체 처리 완료: {restaurant} {date} - {success_slots}/{total_slots} 슬롯 성공")

    def _extract_time_slot(self, menu_slot: str, restaurant: RestaurantType) -> Optional[TimeSlot]:
        """메뉴 슬롯에서 시간대를 추출합니다. (Strategy Pattern 사용)"""
        try:
            strategy = TimeSlotStrategyFactory.get_strategy(restaurant)
            return strategy.extract_time_slot(menu_slot)
        except ValueError as e:
            logger.error(f"지원하지 않는 식당 타입: {e}")
            return None
