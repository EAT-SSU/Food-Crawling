from abc import ABC, abstractmethod
from typing import List

from functions.shared.models.menu import RawMenuData, ParsedMenuData, RestaurantType, TimeSlot


class MenuScraperInterface(ABC):
    @abstractmethod
    async def scrape_menu(self, date: str) -> RawMenuData:
        pass


class MenuParserInterface(ABC):
    @abstractmethod
    async def parse_menu(self, raw_menu: RawMenuData) -> ParsedMenuData:
        pass


class APIClientInterface(ABC):
    @abstractmethod
    async def post_menu(self, date: str, restaurant: RestaurantType, time_slot: TimeSlot,
                        menus: List[str], price: int) -> bool:
        pass


class NotificationClientInterface(ABC):  # 이게 빠져있었네요!
    @abstractmethod
    async def send_notification(self, message: str, channel: str = "#api-notification") -> bool:
        pass

    @abstractmethod
    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        pass

    @abstractmethod
    async def send_error_notification(self, error: Exception) -> bool:
        pass
