from abc import ABC, abstractmethod
from typing import List, Union, Optional, Dict, Any

from functions.shared.models.model import RawMenuData, ParsedMenuData, RestaurantType, TimeSlot


class MenuScraperInterface(ABC):
    @abstractmethod
    async def scrape_menu(self, date: str) -> Union[RawMenuData, List[RawMenuData]]:
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

    @abstractmethod
    async def get_menu(self, date: str, restaurant: RestaurantType, time_slot: TimeSlot) -> Optional[Dict[str, Any]]:
        pass


class NotificationClientInterface(ABC):
    @abstractmethod
    async def send_notification(self, message: str, channel: str = "#api-notification") -> bool:
        pass

    @abstractmethod
    async def send_menu_notification(self, parsed_menu: ParsedMenuData) -> bool:
        pass

    @abstractmethod
    async def send_error_notification(self,exception: Exception,date:Optional[str]=None,restaurant_type:Optional[RestaurantType]=None) -> bool:
        pass
