import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional


class RestaurantType(Enum):
    HAKSIK = ("학생식당", "HAKSIK", 1)
    DODAM = ("도담식당", "DODAM", 2)
    FACULTY = ("교직원식당", "FACULTY", 7)
    DORMITORY = ("기숙사식당", "DORMITORY", None)  # 숭실대 생협 API에 없음

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
    ONE_DOLLAR_MORNING = "MORNING"  # 학생식당 전용
    LUNCH = "LUNCH"
    DINNER = "DINNER"

    def __init__(self, english_name: str):
        self.english_name = english_name


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
    def get_available_times(cls, restaurant: RestaurantType) -> List[TimeSlot]:
        """특정 식당에서 이용 가능한 시간대 반환"""
        return list(cls.PRICES.get(restaurant, {}).keys())


@dataclass
class RawMenuData:
    """웹사이트에서 파싱한 원시 메뉴 데이터"""
    date: str
    restaurant: RestaurantType
    menu_texts: Dict[str, str]  # 키: 메뉴 슬롯(ex: '중식1'), 값: 텍스트 내용


@dataclass
class ParsedMenuData:
    """GPT로 파싱된 메뉴 데이터 - 순수 데이터 + 자체 분석 메서드"""
    date: str
    restaurant: RestaurantType
    menus: Dict[str, List[str]]  # 키: 메뉴 슬롯, 값: 메뉴 항목 리스트
    success: bool = True
    error_slots: Dict[str, str] = field(default_factory=dict)  # 키: 실패한 슬롯, 값: 오류 메시지

    def get_successful_slots(self) -> List[str]:
        """성공적으로 파싱된 슬롯 목록 (GPT에서 오류도 안나고 value가 빈칸이 아닌 것들)"""
        return [slot for slot in self.menus.keys() if slot not in self.error_slots and self.menus[slot]]

    def get_all_slots(self) -> List[str]:
        """모든 슬롯 목록"""
        return list(self.menus.keys())

    def is_complete_success(self) -> bool:
        """완전 성공인지 확인"""
        return len(self.error_slots) == 0 and bool(self.menus)

    def is_partial_success(self) -> bool:
        """부분 성공인지 확인"""
        successful = self.get_successful_slots()
        total = len(self.menus)
        return 0 < len(successful) < total


@dataclass
class RequestBody:
    """API 요청 바디"""
    price: int
    menuNames: List[str] = field(default_factory=list)


class ResponseBuilder:
    """Lambda 응답 생성 전용"""

    @staticmethod
    def create_success_response(parsed_menu: ParsedMenuData,
                                status_code: Optional[int] = None,
                                message: Optional[str] = None,
                                special_note: Optional[str] = None) -> Dict[str, Any]:
        """성공 응답 생성"""
        is_success = parsed_menu.is_complete_success()

        if status_code is None:
            status_code = 200 if is_success else 400

        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps({
                'success': is_success,
                'date': parsed_menu.date,
                'restaurant': parsed_menu.restaurant.korean_name,
                'menus': parsed_menu.menus,
                'parsing_errors': parsed_menu.error_slots if parsed_menu.error_slots else None,
                'message': message or f"{parsed_menu.restaurant.korean_name} 메뉴 처리 완료",
                'special_note': special_note
            }, ensure_ascii=False)
        }

    @staticmethod
    def create_error_response(date: str, restaurant: RestaurantType,
                              error: Exception, status_code: int = 400,
                              message: Optional[str] = None) -> Dict[str, Any]:
        """에러 응답 생성"""
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
                'error': str(error) if error else "Unknown error",
                'error_type': type(error).__name__ if error else "UnknownError"
            }, ensure_ascii=False)
        }
