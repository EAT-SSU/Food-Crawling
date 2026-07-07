import logging
from dataclasses import asdict

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.shared.models.exceptions import MenuPostException
from functions.shared.models.model import RequestBody, RestaurantType, TimeSlot
from functions.shared.repositories.interfaces import APIClientInterface

logger = logging.getLogger(__name__)


class SpringAPIClient(APIClientInterface):
    """Spring Boot API 클라이언트"""

    def __init__(self, base_url: str):
        self.base_url = base_url

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True)
    async def post_menu(self, date: str, restaurant: RestaurantType, time_slot: TimeSlot,
                        menus: list, price: int) -> bool:
        # 서버가 멱등(중복 식단 무시)이므로 존재 확인 없이 곧바로 전송한다.
        logger.info(f"Spring API 메뉴 전송: {restaurant} {time_slot} {date}")

        try:
            form_data = asdict(RequestBody(price=price, menuNames=menus))
            params = {
                "date": date,
                "restaurant": restaurant.english_name,
                "time": time_slot.english_name
            }

            post_url = f"{self.base_url.rstrip('/')}/meals/with-price"

            async with aiohttp.ClientSession() as session:
                async with session.post(
                        post_url,
                        json=form_data,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()

            logger.info(f"Spring API 메뉴 전송 성공: {restaurant} {time_slot} {date}")
            return True

        except Exception as e:
            logger.error(f"Spring API 메뉴 전송 실패: {e}")
            raise MenuPostException(
                target_date=date,
                restaurant_type=restaurant,
                details=f"Spring API 메뉴 전송 실패:{e}"
            )
