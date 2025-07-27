import logging
from dataclasses import asdict
from typing import Optional, Dict, Any

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.shared.models.model import RequestBody, RestaurantType, TimeSlot
from functions.shared.repositories.interfaces import APIClientInterface

logger = logging.getLogger(__name__)


class SpringAPIClient(APIClientInterface):
    """Spring Boot API 클라이언트"""

    def __init__(self, base_url: str):
        self.base_url = base_url

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def post_menu(self, date: str, restaurant: RestaurantType, time_slot: TimeSlot,
                        menus: list, price: int) -> bool:
        """메뉴를 Spring API에 전송합니다."""
        logger.info(f"Spring API 메뉴 전송: {restaurant} {time_slot} {date}")

        try:
            form_data = asdict(RequestBody(price=price, menuNames=menus))
            params = {
                "date": date,
                "restaurant": restaurant.english_name,
                "time": time_slot.english_name
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

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    async def get_menu(self, date: str, restaurant: RestaurantType, time_slot: TimeSlot) -> Optional[Dict[str, Any]]:
        """Spring API에서 메뉴를 조회합니다."""
        logger.info(f"Spring API 메뉴 조회: {restaurant} {time_slot} {date}")

        try:
            params = {
                "date": date,
                "restaurant": restaurant.english_name,
                "time": time_slot.english_name
            }

            get_url = f"{self.base_url.rstrip('/')}/meals"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                        get_url,
                        params=params,
                        headers={
                            'Accept': 'application/json',
                            'Accept-Language': 'ko,en-US;q=0.9,en;q=0.8',
                            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 404:
                        logger.warning(f"Spring API 메뉴 없음: {restaurant} {time_slot} {date}")
                        return None

                    response.raise_for_status()
                    data = await response.json()

            logger.info(f"Spring API 메뉴 조회 성공: {restaurant} {time_slot} {date}")
            return data

        except Exception as e:
            logger.error(f"Spring API 메뉴 조회 실패: {e}")
            raise
