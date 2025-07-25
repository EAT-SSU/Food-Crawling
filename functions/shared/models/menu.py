import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class RestaurantType(Enum):
    HAKSIK = ("학생식당", "HAKSIK", 1)
    DODAM = ("도담식당", "DODAM", 2)
    FACULTY = ("교직원식당", "FACULTY", 7)
    DORMITORY = ("기숙사식당","DORMITORY", None)  # 숭실대 생협 API에 없음

    def __init__(self, korean_name: str, english_name: str, soongguri_rcd: Optional[int]):
        self.korean_name = korean_name
        self.english_name = english_name
        self.soongguri_rcd = soongguri_rcd

    @property
    def lambda_base_url(self) -> str:
        """AWS Lambda 기본 URL"""
        url_map = {
            RestaurantType.DODAM: os.getenv("DODAM_LAMBDA_BASE_URL"),
            RestaurantType.HAKSIK: os.getenv("HAKSIK_LAMBDA_BASE_URL"),
            RestaurantType.FACULTY: os.getenv("FACULTY_LAMBDA_BASE_URL"),
            RestaurantType.DORMITORY: os.getenv("DORMITORY_LAMBDA_BASE_URL"),
        }
        return url_map[self]


class TimeSlot(Enum):
    ONE_DOLLAR_MORNING = ("1000원 조식", "1M", "ONE_DOLLAR_MORNING")  # 학생식당 전용
    LUNCH = ("점심", "L", "LUNCH")
    DINNER = ("저녁", "D", "DINNER")

    def __init__(self, korean_name: str, code: str, english_name: str):
        self.korean_name = korean_name
        self.code = code
        self.english_name = english_name

    @classmethod
    def parse(cls, value: str) -> 'TimeSlot':
        for slot in cls:
            if value in [slot.korean_name, slot.code, slot.english_name]:
                return slot
        raise ValueError(f"Unknown time slot: {value}")


class MenuPricing:
    """메뉴 가격 관리"""

    PRICES: Dict[RestaurantType, Dict[TimeSlot, int]] = {
        RestaurantType.DODAM: {
            TimeSlot.LUNCH: 6000,
            TimeSlot.DINNER: 6000,
        },
        RestaurantType.HAKSIK: {
            TimeSlot.ONE_DOLLAR_MORNING: 1000,
            TimeSlot.LUNCH: 5000,
            TimeSlot.DINNER: 5000,
        },
        RestaurantType.FACULTY: {
            TimeSlot.LUNCH: 7000,
        },
        RestaurantType.DORMITORY: {
            TimeSlot.LUNCH: 5500,
            TimeSlot.DINNER: 5500,
        },
    }

    @classmethod
    def get_price(cls, restaurant: RestaurantType, time_slot: TimeSlot) -> Optional[int]:
        """특정 식당의 특정 시간대 가격 반환"""
        return cls.PRICES.get(restaurant, {}).get(time_slot)

    @classmethod
    def get_available_times(cls, restaurant: RestaurantType) -> list[TimeSlot]:
        """특정 식당에서 이용 가능한 시간대 반환"""
        return list(cls.PRICES.get(restaurant, {}).keys())


@dataclass
class RawMenuData:
    """웹사이트에서 파싱한 원시 메뉴 데이터"""
    date: str
    restaurant: RestaurantType
    menu_texts: Dict[str, str]  # 키: 메뉴 슬롯(ex: '중식1'), 값: 텍스트 내용


import json
from dataclasses import dataclass, field
from typing import Dict, List, Any


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

    def to_lambda_response(self, status_code: int = None, message: str = None,
                           special_note: str = None) -> Dict[str, Any]:
        """Lambda 응답 형태로 변환"""
        if status_code is None:
            status_code = 200 if self.success else 400

        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps({
                'success': self.success,
                'date': self.date,
                'restaurant': self.restaurant.korean_name,
                'menus': self.menus,
                'parsing_errors': self.error_slots if self.error_slots else None,
                'message': message or f"{self.restaurant.korean_name} 메뉴 처리 완료",
                'special_note': special_note
            }, ensure_ascii=False)
        }

    @classmethod
    def error_response(cls, date: str, restaurant: RestaurantType, error: Exception,
                       status_code: int = 400, message: str = None) -> Dict[str, Any]:
        """에러 응답 생성 (클래스 메서드)"""
        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps({
                'success': False,
                'date': date,
                'restaurant': restaurant.korean_name if restaurant else "unknown",
                'menus': {},
                'parsing_errors': None,
                'message': message or f"{restaurant.korean_name if restaurant else 'Unknown'} 메뉴 처리 실패",
                'error': str(error),
                'error_type': type(error).__name__
            }, ensure_ascii=False)
        }


@dataclass
class RequestBody:
    price: int
    menuNames: List[str] = field(default_factory=list)
