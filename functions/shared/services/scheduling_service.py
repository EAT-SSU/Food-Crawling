import logging
from typing import List

from functions.shared.models.exceptions import HolidayException, MenuFetchException, MenuPostException, \
    MenuParseException, WeirdRestaurantNameException
from functions.shared.models.model import RestaurantType, ParsedMenuData

logger = logging.getLogger(__name__)


class SchedulingService:
    """스케줄링 서비스 - 직접 함수 호출 방식"""

    def __init__(self, notification_service, scraping_service):
        self.notification_service = notification_service
        self.scraping_service = scraping_service

    async def process_weekly_schedule_general(self, restaurant_type: RestaurantType, weekdays: List[str]) -> List[
        ParsedMenuData]:
        """일반 식당 주간 스케줄 처리 (도담, 학생, 교직원)"""
        logger.info(f"{restaurant_type.korean_name} 주간 스케줄 처리 시작: {weekdays}")

        parsed_menus: List[ParsedMenuData] = []
        scraping_service = self.scraping_service

        # 각 날짜별로 일반 식당 처리
        # 하부에서는 예외처리 하지 않는다. 모든 예외는 이곳에서 처리한다. 이는 비즈니스의 로직의 특성상 스케줄링은 일부라도 성공해야만 한다.
        for date in weekdays:
            try:
                parsed_menu = await scraping_service.scrape_and_process(date, restaurant_type)
                parsed_menus.append(parsed_menu)
                await self.notification_service.send_menu_notification(parsed_menu)

            except (HolidayException, MenuFetchException, MenuParseException,
                WeirdRestaurantNameException, MenuPostException) as e:
                logger.warning(f"{restaurant_type.korean_name}({date}) 처리 실패: {type(e).__name__} - {e}")
                await self.notification_service.send_error_notification(e, date, restaurant_type)
                continue
            except Exception as e:
                # 예상치 못한 예외 - 더 자세한 로깅
                logger.error(f"{restaurant_type.korean_name}({date}) 예상치 못한 오류: {type(e).__name__} - {e}", exc_info=True)
                await self.notification_service.send_error_notification(e, date, restaurant_type)
                continue
        # Slack 알림 전송

        for parsed_menu in parsed_menus:
            if parsed_menu.error_slots:
                logger.info(f"{restaurant_type.korean_name}({parsed_menu.date}) 부분 실패: {parsed_menu.error_slots}")
                for slot, error in parsed_menu.error_slots.items():
                    await self.notification_service.send_error_notification(
                        exception=Exception(f"[{slot}] {error}"),
                        date=parsed_menu.date,
                        restaurant_type=restaurant_type
                    )

        logger.info(f"{restaurant_type.korean_name} 주간 스케줄 처리 완료")
        return parsed_menus

    async def process_weekly_schedule_dormitory(self, weekdays: List[str]) -> List[ParsedMenuData]:
        """기숙사식당 주간 스케줄 처리 (주간 단위)"""
        restaurant_type = RestaurantType.DORMITORY
        logger.info(f"{restaurant_type.korean_name} 주간 스케줄 처리 시작: {weekdays}")

        results = {}
        scraping_service = self.scraping_service
        date = weekdays[0]  # 월요일 날짜를 기반으로 일주일 전체가 스크래핑 됨

        try:
            parsed_menus: List[ParsedMenuData] = await scraping_service.scrape_and_process_dormitory(date)

            for parsed_menu in parsed_menus:
                if parsed_menu.error_slots:
                    logger.info(
                        f"{restaurant_type.korean_name}({parsed_menu.date}) 부분 실패: {parsed_menu.error_slots}")
                    for slot, error in parsed_menu.error_slots.items():
                        await self.notification_service.send_error_notification(
                            exception=Exception(f"[{slot}] {error}"),
                            date=parsed_menu.date,
                            restaurant_type=restaurant_type
                        )
                else:
                    await self.notification_service.send_menu_notification(parsed_menu)

            return parsed_menus
        except Exception as e:
            results[date] = {
                "success": False,
                "error": str(e)
            }
            logger.error(f"{restaurant_type.korean_name} {date} 처리 실패: {e}")

        

        logger.info(f"{restaurant_type.korean_name} 주간 스케줄 처리 완료")
        return results
