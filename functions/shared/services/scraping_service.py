import logging
from typing import Optional

from functions.shared.models.menu import RestaurantType, TimeSlot, MenuPricing, ParsedMenuData
from functions.shared.services.time_slot_strategy import TimeSlotStrategyFactory

logger = logging.getLogger(__name__)


class ScrapingService:
    """메뉴 스크래핑 서비스"""

    def __init__(self, container):
        self._container = container

    async def scrape_and_process(self, date: str, restaurant_type: RestaurantType,
                                 is_dev: bool = False) -> ParsedMenuData:
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

        # 4. API 전송 (식당별 특수 로직 적용)
        await self._send_menus_to_api(parsed_menu, is_dev)
        logger.info(f"API 전송 완료: {restaurant_type.korean_name} {date}")

        return parsed_menu

    async def _send_menus_to_api(self, parsed_menu: ParsedMenuData, is_dev: bool) -> None:
        """파싱된 메뉴를 API에 전송합니다."""
        restaurant = parsed_menu.restaurant
        date = parsed_menu.date

        for menu_slot, menu_items in parsed_menu.menus.items():
            if not menu_items:
                continue

            # 식당별 특수 로직 적용
            time_slot = self._extract_time_slot(menu_slot, restaurant)
            if not time_slot:
                logger.warning(f"시간대를 확인할 수 없는 메뉴 슬롯: {menu_slot}")
                continue

            price = MenuPricing.get_price(restaurant, time_slot)
            if not price:
                logger.warning(f"가격 정보가 없음: {restaurant.korean_name} {time_slot.korean_name}")
                continue

            if is_dev:
                # 개발 환경만 전송
                dev_client = self._container.get_api_client(is_dev=True)
                await dev_client.post_menu(
                    date=date,
                    restaurant=restaurant.english_name,
                    time_slot=time_slot.english_name,
                    menus=menu_items,
                    price=price
                )
                logger.debug(f"개발 API 전송 완료: {restaurant.english_name} {time_slot.english_name}")
            else:
                # 프로덕션 + 개발 둘 다 전송
                prod_client = self._container.get_api_client(is_dev=False)
                dev_client = self._container.get_api_client(is_dev=True)

                await prod_client.post_menu(
                    date=date,
                    restaurant=restaurant.english_name,
                    time_slot=time_slot.english_name,
                    menus=menu_items,
                    price=price
                )

                await dev_client.post_menu(
                    date=date,
                    restaurant=restaurant.english_name,
                    time_slot=time_slot.english_name,
                    menus=menu_items,
                    price=price
                )
                logger.debug(f"프로덕션+개발 API 전송 완료: {restaurant.english_name} {time_slot.english_name}")

    def _extract_time_slot(self, menu_slot: str, restaurant: RestaurantType) -> Optional[TimeSlot]:
        """메뉴 슬롯에서 시간대를 추출합니다. (Strategy Pattern 사용)"""

        try:
            strategy = TimeSlotStrategyFactory.get_strategy(restaurant)
            return strategy.extract_time_slot(menu_slot)
        except ValueError as e:
            logger.error(f"지원하지 않는 식당 타입: {e}")
            return None

# 🎯 Food Scrapper 리팩토링 TODO 리스트
# ✅ 완료된 작업들
# Phase 1: 기반 구조 구축
#
# ✅ 새 디렉토리 구조 생성 - DRF 스타일 적용
# ✅ 설정 및 DI 컨테이너 구현 - config/settings.py, config/dependencies.py
# ✅ 공통 모델 분리 - shared/models/menu.py, shared/models/exceptions.py
# ✅ 인터페이스 정의 - shared/repositories/interfaces.py
#
# Phase 2: Repository 레이어 구현
#
# ✅ 웹 스크래퍼 구현 - 모든 식당별 스크래퍼 완성
#
# ✅ DodamScraper (Settings 적용)
# ✅ HaksikScraper (Settings 적용)
# ✅ FacultyScraper (Settings 적용)
# ✅ DormitoryScraper (Settings 적용, 특수 파싱 로직)
#
#
# ✅ 클라이언트 구현 - 모든 외부 연동 클라이언트 완성
#
# ✅ GPTClient (Settings에서 프롬프트/모델 로드)
# ✅ SpringAPIClient
# ✅ SlackClient
#
#
#
# Phase 3: Service 레이어 구현
#
# ✅ ScrapingService 구현 - 식당별 특수 로직 포함
# ✅ NotificationService 구현 - 알림 관련 로직
# ✅ SchedulingService 구현 - 공통 스케줄링 로직 (중복 제거)
#
# Phase 4: View 레이어 구현
#
# ✅ 모든 식당 스크래핑 뷰 완성
#
# ✅ scraping/views/dodam.py
# ✅ scraping/views/haksik.py
# ✅ scraping/views/faculty.py
# ✅ scraping/views/dormitory.py
#
#
# ✅ 모든 식당 스케줄링 뷰 완성
#
# ✅ scheduling/views/dodam.py
# ✅ scheduling/views/haksik.py
# ✅ scheduling/views/faculty.py
# ✅ scheduling/views/dormitory.py
#
#
#
# Phase 5: 응답 구조 통일
#
# ✅ ParsedMenuData에 응답 메서드 추가 - 변환 레이어 제거
# ✅ 통일된 응답 구조 - 모든 뷰에서 일관된 응답
# ✅ 비즈니스 로직 정리 - 식당별 운영 시간 반영
#
#
# 🔄 진행 중인 작업
# 운영 시간 로직 개선
#
# 🔄 식당별 운영 시간 설정 방식 개선 - 현재 하드코딩된 if-else 구조 개선 필요
#
#
# 📋 남은 TODO 작업들
# Phase 6: 코드 품질 개선
#
# TODO: 운영 시간 관리 시스템 개선 - 설정 기반 방식으로 리팩토링
#
# TODO: RESTAURANT_OPERATING_HOURS 설정 추가
# TODO: _extract_time_slot 메서드 리팩토링 (if-else 제거)
# TODO: 운영 시간 검증 로직 분리
#
#
#
# Phase 7: 유틸리티 함수 정리
#
# TODO: 누락된 유틸리티 함수들 구현
#
# TODO: shared/utils/parsing_utils.py의 parse_table_to_dict 오버로드 정리
# TODO: shared/utils/date_utils.py 완성도 검증
# TODO: shared/utils/response_utils.py 필요성 재검토
#
#
#
# Phase 8: 테스트 구현
#
# TODO: 단위 테스트 작성
#
# TODO: ScrapingService 테스트
# TODO: 각 Scraper 테스트 (목 데이터 사용)
# TODO: GPTClient 테스트 (OpenAI API 목킹)
# TODO: DI Container 테스트
#
#
# TODO: 통합 테스트 작성
#
# TODO: 전체 스크래핑 플로우 테스트
# TODO: 스케줄링 플로우 테스트
# TODO: 에러 처리 시나리오 테스트
#
#
#
# Phase 9: SAM 전환 완료
#
# TODO: SAM template.yaml 완성
#
# TODO: 모든 Lambda 함수 Handler 경로 업데이트
# TODO: 환경별 배포 설정 (dev/prod)
# TODO: CloudWatch 알람 설정
# TODO: API Gateway 설정 완성
#
#
# TODO: 배포 자동화
#
# TODO: GitHub Actions 워크플로우 설정
# TODO: 환경별 Parameter Store 설정
# TODO: 배포 스크립트 작성 (Makefile 완성)
#
#
#
# Phase 10: 문서화 및 최종 정리
#
# TODO: README.md 업데이트 - 새로운 구조 반영
# TODO: API 문서 작성 - 각 Lambda 엔드포인트 문서화
# TODO: 아키텍처 다이어그램 업데이트 - Mermaid로 새 구조 표현
# TODO: 배포 가이드 작성 - SAM 기반 배포 방법 문서화
#
# Phase 11: 성능 최적화 (선택사항)
#
# TODO: Lambda Cold Start 최적화 - Layer 크기 최적화
# TODO: 병렬 처리 개선 - 스케줄링에서 더 효율적인 병렬 처리
# TODO: 에러 처리 개선 - 더 세분화된 예외 처리
# TODO: 로깅 시스템 개선 - 구조화된 로깅 적용
#
# Phase 12: 모니터링 및 알림 (선택사항)
#
# TODO: CloudWatch 대시보드 구성 - 메뉴 처리 성공/실패 현황
# TODO: 알람 시스템 개선 - 더 상세한 Slack 알림
# TODO: 메트릭 수집 - 처리 시간, 성공률 등 수집
#
