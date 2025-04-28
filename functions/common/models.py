# models.py
from typing import Literal

# 리터럴 타입 정의
RestaurantType = Literal["도담식당", "학생식당", "기숙사식당"]
TimeSlotPrefix = Literal["중식", "석식"]
StatusType = Literal["success", "error"]

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Any

# 식당 타입 정의
RestaurantType = Literal["도담식당", "학생식당", "기숙사식당"]


@dataclass
class RawMenuData:
    """웹사이트에서 파싱한 원시 메뉴 데이터"""
    date: str
    restaurant: RestaurantType
    menu_texts: Dict[str, str]  # 키: 메뉴 슬롯(ex: '중식1'), 값: 텍스트 내용


@dataclass
class ParsedMenuData:
    """GPT로 파싱된 메뉴 데이터"""
    date: str
    restaurant: RestaurantType
    menus: Dict[str, List[str]]  # 키: 메뉴 슬롯(ex: '중식1'), 값: 메뉴 항목 리스트
    success: bool = True
    error_slots: Dict[str, str] = field(default_factory=dict)  # 키: 실패한 슬롯, 값: 오류 메시지

    @property
    def is_empty(self) -> bool:
        """메뉴가 모두 비어있는지 확인"""
        return all(not menu_items for menu_items in self.menus.values())

    @property
    def successful_slots(self) -> List[str]:
        """성공적으로 파싱된 슬롯 목록"""
        return [slot for slot in self.menus.keys() if slot not in self.error_slots]

    @property
    def all_slots(self) -> List[str]:
        """모든 슬롯 목록"""
        return list(self.menus.keys())

    def get_slot_status(self, slot: str) -> Dict[str, Any]:
        """특정 슬롯의 파싱 상태 정보"""
        if slot not in self.menus:
            return {"exists": False}

        return {
            "exists": True,
            "success": slot not in self.error_slots,
            "menu_items": self.menus.get(slot, []),
            "error": self.error_slots.get(slot)
        }

    def add_menu_items(self, slot: str, items: List[str]) -> None:
        """슬롯에 메뉴 항목 추가 (파싱 성공 시)"""
        self.menus[slot] = items
        # 이전에 오류가 있었다면 제거
        if slot in self.error_slots:
            del self.error_slots[slot]

    def add_error(self, slot: str, error_message: str) -> None:
        """슬롯 파싱 실패 시 오류 추가"""
        self.error_slots[slot] = error_message
        # 메뉴 항목은 빈 리스트로 설정
        self.menus[slot] = []
        # 하나라도 오류가 있으면 전체 성공 상태 업데이트
        self.success = False

@dataclass
class RequestBody:
    price: int
    menuNames: List[str] = field(default_factory=list)

