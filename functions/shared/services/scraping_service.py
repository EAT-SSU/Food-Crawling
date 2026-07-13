import asyncio
from typing import Optional, List

from functions.shared.models.exceptions import MenuPostException, RetryableApiSendError
from functions.shared.models.model import (
    MenuPricing,
    ParsedMenuData,
    ProcessingOutcome,
    RawMenuData,
    RestaurantType,
    SlotProcessingResult,
    TimeSlot,
)
from functions.shared.observability import emit_event
from functions.shared.repositories.clients.spring_api_client import SpringAPIClient
from functions.shared.services.time_slot_strategy import TimeSlotStrategyFactory


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
        emit_event(
            "INFO",
            "scraping_process_started",
            "scraping",
            restaurant=restaurant_type.english_name,
            date=date,
            environment="dev" if is_dev else "prod",
        )

        # 1. 스크래핑 단계 (HTML 추출 + GPT 파싱)
        parsed_menu = await self.scrape_menu(date, restaurant_type)

        # 2. API 전송 단계
        await self.send_to_api(parsed_menu, is_dev)

        emit_event(
            "INFO",
            "scraping_process_completed",
            "scraping",
            restaurant=restaurant_type.english_name,
            date=date,
            environment="dev" if is_dev else "prod",
        )
        return parsed_menu

    async def scrape_and_process_dormitory(self, date: str, is_dev: bool = True) -> List[ParsedMenuData]:
        """기숙사식당 전용 메뉴 스크래핑부터 API 전송까지 전체 프로세스"""
        emit_event(
            "INFO",
            "scraping_process_started",
            "scraping",
            restaurant=RestaurantType.DORMITORY.english_name,
            date=date,
            environment="dev" if is_dev else "prod",
        )

        # 1. 스크래핑 단계 (주간)
        parsed_menus = await self.scrape_dormitory_weekly(date)

        # 2. API 전송 단계 (각 날짜별) - 한 날짜의 전송 실패가 나머지 주를 중단시키지 않도록 격리
        send_failed_days = 0
        for parsed_menu in parsed_menus:
            try:
                await self.send_to_api(parsed_menu, is_dev)
            except MenuPostException:
                send_failed_days += 1
                continue

        # 하루라도 전송에 실패하면 주 전체를 재시도한다. 서버가 멱등이라 이미 성공한 날은 중복 무시되므로 안전하다
        if send_failed_days > 0:
            raise RetryableApiSendError(
                target_date=date,
                restaurant_type=RestaurantType.DORMITORY,
                failed_days=send_failed_days,
            )

        emit_event(
            "INFO",
            "scraping_process_completed",
            "scraping",
            restaurant=RestaurantType.DORMITORY.english_name,
            date=date,
            date_count=len(parsed_menus),
            environment="dev" if is_dev else "prod",
        )
        return parsed_menus

    async def scrape_menu(self, date: str, restaurant_type: RestaurantType) -> ParsedMenuData:
        """
        메뉴 스크래핑: HTML 추출 + GPT 파싱까지 완료
        (테스트하기 쉬운 완전한 단위)
        """
        emit_event(
            "INFO",
            "scraping_started",
            "source_fetch",
            restaurant=restaurant_type.english_name,
            date=date,
        )

        # 1. HTML 추출
        raw_menu = await self._extract_raw_menu(date, restaurant_type)

        # 2. GPT 파싱
        parsed_menu = await self._parse_menu(raw_menu)

        # 3. 결과 로깅
        self._log_scraping_result(parsed_menu)

        return parsed_menu

    async def scrape_dormitory_weekly(self, date: str) -> List[ParsedMenuData]:
        """
        기숙사 주간 스크래핑: HTML 추출 + GPT 파싱까지 완료
        (테스트하기 쉬운 완전한 단위)
        """
        emit_event(
            "INFO",
            "scraping_started",
            "source_fetch",
            restaurant=RestaurantType.DORMITORY.english_name,
            date=date,
        )

        # 1. HTML 추출 (주간)
        raw_menus = await self._extract_dormitory_weekly(date)

        # 2. GPT 파싱 (각 날짜별)
        parsed_menus = []
        for raw_menu in raw_menus:
            parsed_menu = await self._parse_menu(raw_menu)
            parsed_menus.append(parsed_menu)
            self._log_scraping_result(parsed_menu)

        return parsed_menus

    async def send_to_api(self, parsed_menu: ParsedMenuData, is_dev: bool = True) -> None:
        """
        파싱된 메뉴를 API에 전송하고 결과를 ParsedMenuData에 반영
        """
        emit_event(
            "INFO",
            "api_send_started",
            "menu_post",
            restaurant=parsed_menu.restaurant.english_name,
            date=parsed_menu.date,
            environment="dev" if is_dev else "prod",
        )

        clients: List[SpringAPIClient] = [self._dev_api_client]
        if not is_dev:  # 운영 환경
            clients.append(self._prod_api_client)

        # 운영 반영이 목표인 클라이언트만 슬롯 성패를 좌우한다(운영 스케줄=prod, 개발 실행=dev)
        critical_client = self._prod_api_client if not is_dev else self._dev_api_client

        restaurant, date = parsed_menu.restaurant, parsed_menu.date
        sent_count = 0
        failed_slots = []
        successful_slots = parsed_menu.get_successful_slots()

        for slot, menu in successful_slots.items():
            time_slot = self._extract_time_slot(slot, restaurant)
            if not time_slot:
                continue

            price = MenuPricing.get_price(restaurant, time_slot)
            if not price:
                continue

            menu_items = parsed_menu.menus[slot]

            results = await asyncio.gather(*[
                client.post_menu(date, restaurant, time_slot, menu_items, price)
                for client in clients
            ], return_exceptions=True)

            critical_error = None
            for client, result in zip(clients, results):
                if isinstance(result, Exception):
                    is_critical = client is critical_client
                    if is_critical:
                        critical_error = result

            if critical_error is not None:
                parsed_menu.error_slots[slot] = critical_error
                parsed_menu.slot_results[slot] = self._api_slot_result(
                    parsed_menu.slot_results.get(slot),
                    slot,
                    ProcessingOutcome.API_FAILURE,
                    "POST_ERROR",
                    type(critical_error).__name__,
                )
                failed_slots.append(slot)
                continue

            sent_count += 1
            parsed_menu.error_slots.pop(slot, None)
            parsed_menu.slot_results[slot] = self._api_slot_result(
                parsed_menu.slot_results.get(slot),
                slot,
                ProcessingOutcome.SUCCESS,
                "POST_SUCCESS",
            )

        # 전체 성공 여부 업데이트
        if failed_slots:
            parsed_menu.success = False

        # API 전송이 모두 실패했다면 예외 발생
        if sent_count == 0 and successful_slots:
            raise MenuPostException(
                target_date=parsed_menu.date,
                restaurant_type=restaurant,
                details=None,
            )

        emit_event(
            "INFO" if not failed_slots else "WARNING",
            "api_send_completed",
            "menu_post",
            restaurant=restaurant.english_name,
            date=date,
            environment="dev" if is_dev else "prod",
            success_count=sent_count,
            failure_count=len(failed_slots),
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
        parsed_menu = await self._parser.parse_menu(raw_menu)
        parsed_menu.slot_results = {
            **raw_menu.slot_results,
            **parsed_menu.slot_results,
        }
        return parsed_menu

    def _log_scraping_result(self, parsed_menu: ParsedMenuData) -> None:
        """스크래핑 결과 로깅"""
        total_slots = len(parsed_menu.get_all_slots())
        success_slots = len(parsed_menu.get_successful_slots())

        emit_event(
            "INFO" if not parsed_menu.error_slots else "WARNING",
            "scraping_completed",
            "parse",
            restaurant=parsed_menu.restaurant.english_name,
            date=parsed_menu.date,
            success_count=success_slots,
            failure_count=len(parsed_menu.error_slots),
            slot_count=total_slots,
        )

    @staticmethod
    def _api_slot_result(
        previous: Optional[SlotProcessingResult],
        slot: str,
        outcome: ProcessingOutcome,
        reason_code: str,
        error_type: Optional[str] = None,
    ) -> SlotProcessingResult:
        return SlotProcessingResult(
            slot=slot,
            stage="menu_post",
            outcome=outcome,
            reason_code=reason_code,
            source_length=previous.source_length if previous else None,
            source_sha256=previous.source_sha256 if previous else None,
            duration_ms=previous.duration_ms if previous else None,
            retry_count=previous.retry_count if previous else None,
            error_type=error_type,
        )

    def _extract_time_slot(self, menu_slot: str, restaurant: RestaurantType) -> Optional[TimeSlot]:
        """메뉴 슬롯에서 시간대를 추출합니다. (Strategy Pattern 사용)"""
        try:
            strategy = TimeSlotStrategyFactory.get_strategy(restaurant)
            return strategy.extract_time_slot(menu_slot)
        except ValueError as error:
            emit_event(
                "ERROR",
                "time_slot_resolution_failed",
                "menu_post",
                restaurant=restaurant.english_name,
                slot=menu_slot,
                **{"error.type": type(error).__name__},
            )
            return None
