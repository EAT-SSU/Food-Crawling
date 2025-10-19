import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """애플리케이션 설정 (dataclass 기반)"""

    # Secret env
    GPT_API_KEY: str
    SLACK_WEBHOOK_URL: str
    API_BASE_URL: str
    DEV_API_BASE_URL: str

    # Scraping data source url
    SOONGGURI_BASE_URL: str = "http://m.soongguri.com/m_req/m_menu.php"
    DORMITORY_BASE_URL: str = "https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php"

    # 숭실대 생협(soonguri)의 api에서 쓰는 구분자
    SOONGGURI_HAKSIK_RCD: int = 1
    SOONGGURI_DODAM_RCD: int = 2
    SOONGGURI_FACULTY_RCD: int = 7

    # 도담식당(점심, 저녁), 학생식당(1000원 조식, 점심), 기숙사식당(아침,점심,저녁)
    DODAM_LUNCH_PRICE: int = 6000
    DODAM_DINNER_PRICE: int = 6000

    HAKSIK_ONE_DOLLAR_MORNING_PRICE: int = 1000
    HAKSIK_MORNING_PRICE: int = 1000
    HAKSIK_LUNCH_PRICE: int = 5000
    HAKSIK_DINNER_PRICE: int = 5000

    FACULTY_LUNCH_PRICE: int = 7000

    DORMITORY_MORNING_PRICE: int = 5500  # 오타 수정: MORING -> MORNING
    DORMITORY_LUNCH_PRICE: int = 5500
    DORMITORY_DINNER_PRICE: int = 5500

    GPT_FUNCTION_TOOLS: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "type": "function",
            "function": {
                "name": "extract_all_menus",  # extract_main_menus -> extract_all_menus로 통일
                "description": "모든 메뉴를 추출하여 리스트로 반환",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "all_menus": {
                            "type": "array",
                            "description": "모든 메뉴 목록 (중복 제거, 특수문자 제외)",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["all_menus"],
                },
            },
        }
    ])

    GPT_SYSTEM_PROMPT: str = """당신은 한국 대학 식당 메뉴 데이터를 정확하게 파싱하는 전문가입니다.

# 작업 (Action)
크롤링한 식당 메뉴 텍스트에서 실제 음식 메뉴명만 추출하여 문자열 배열로 반환하세요.

# 맥락 (Context)
크롤링한 원본 텍스트에는 메뉴명 외에도 영어 번역, 가격 정보, 알러지 정보, 원산지 정보, 홍보성 설명 등이 포함되어 있습니다.
이 데이터는 학생들에게 당일 식사 메뉴를 제공하는 API에 사용되므로, 순수한 음식명만 필요합니다.

# 추출 규칙
1. 포함할 항목: 메인요리, 밥, 국, 찌개, 반찬, 디저트, 음료
2. 제외할 항목: 영어 번역, 가격, 알러지 정보, 원산지 정보, 별표(★) 등 특수기호, 홍보성 설명문
3. '&' 또는 '/' 기호로 연결된 메뉴는 각각 분리하여 개별 메뉴로 추출
4. 각 메뉴명에서 불필요한 특수문자를 제거하고 순수한 한글 메뉴명만 추출
5. 메뉴가 없다고 판단되는 경우 빈 배열을 반환

# 출력 형식 (Format)
extract_all_menus 함수를 사용하여 all_menus 배열로 반환하세요.
"""
    GPT_MODEL: str = "gpt-4o-mini"

    FACULTY_EXAMPLE_RAW_MENU = """부드러운 순두부와 차돌박이를 듬뿍 넣어 청양고추와 달걀을 넣고 뚝배기에 보글보글 얼큰하게 끓인 ~! ★부드러운 닭다리살과 넙적당면을 단짠단짠 맛있는 소스에 조려 얼큰한 순두부찌개에 찰떡궁합 ~! 뚝배기차돌순두부찌개 & 안동찜닭 - 7.0 Ttukbaegi soft tofu stew & Andong Braised Chicken 부들어묵볶음 유자부추무침 포기김치 보리차 쌀밥 당근사과주스 *알러지유발식품: 뚝배기순두부찌개(우육,대두,계란), 안동찜닭(계육), 포기김치(새우) *원산지: 뚝배기순두부찌개(우육:미국산,대두:외국산,계란:국산), 안동찜닭(계육:브라질산), 포기김치(배추,고추분:국산)"""
    FACULTY_EXAMPLE_PARSED_MENU = "['안동찜닭', '뚝배기차돌순두부찌개', '부들어묵볶음', '유자부추무침', '포기김치', '보리차', '쌀밥', '당근사과주스']"

    @classmethod
    def from_env(cls) -> 'Settings':
        """환경 변수에서 설정을 로드합니다."""
        # .env 파일 로드 (기존 환경변수는 덮어쓰지 않음)
        env_path = Path(__file__).parent.parent.parent / '.env'
        load_dotenv(dotenv_path=env_path, override=False)

        return cls(
            GPT_API_KEY=cls._get_required_env("GPT_API_KEY"),
            SLACK_WEBHOOK_URL=cls._get_required_env("SLACK_WEBHOOK_URL"),
            API_BASE_URL=cls._get_required_env("API_BASE_URL"),
            DEV_API_BASE_URL=cls._get_required_env("DEV_API_BASE_URL"),
        )

    @staticmethod
    def _get_required_env(key: str) -> str:
        """필수 환경 변수를 가져옵니다."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value


# 전역 설정 인스턴스
def get_settings() -> Settings:
    """설정 인스턴스를 반환합니다."""
    return Settings.from_env()
