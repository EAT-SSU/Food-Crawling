import logging
from dataclasses import asdict

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.shared.models.menu import RequestBody
from functions.shared.repositories.interfaces import APIClientInterface

logger = logging.getLogger(__name__)


class SpringAPIClient(APIClientInterface):
    """Spring Boot API 클라이언트"""

    def __init__(self, base_url: str):
        self.base_url = base_url

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def post_menu(self, date: str, restaurant: str, time_slot: str,
                        menus: list, price: int) -> bool:
        """메뉴를 Spring API에 전송합니다."""
        logger.info(f"Spring API 메뉴 전송: {restaurant} {time_slot} {date}")

        try:
            form_data = asdict(RequestBody(price=price, menuNames=menus))
            params = {
                "date": date,
                "restaurant": restaurant,
                "time": time_slot
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                        self.base_url,
                        json=form_data,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()

            logger.info(f"Spring API 메뉴 전송 성공: {restaurant} {time_slot} {date}")
            return True

        except Exception as e:
            logger.error(f"Spring API 메뉴 전송 실패: {e}")
            raise