import os
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass(frozen=True)
class Settings:
    """애플리케이션 설정 (dataclass 기반)"""

    # Secret env
    GPT_API_KEY: str
    SLACK_WEBHOOK_URL: str
    API_BASE_URL: str
    DEV_API_BASE_URL: str

    # AWS lambda base url
    DODAM_LAMBDA_BASE_URL: str
    HAKSIK_LAMBDA_BASE_URL: str
    DORMITORY_LAMBDA_BASE_URL: str
    FACULTY_LAMBDA_BASE_URL: str

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

    GPT_SYSTEM_PROMPT: str = """
    당신은 대학교 식당 메뉴 추출 전문가입니다. 주어진 텍스트에서 실제 음식 메뉴만 정확하게 추출해야 합니다.

    추출 규칙:
    1. 실제 음식 이름만 추출 (밥, 국, 찌개, 반찬, 메인요리, 디저트 등)

    2. 다음은 반드시 제외하세요:
       - 식당 이름, 코너 이름 (예: "대면 코너", "도담 식당")
       - 공지사항, 안내문구 (예: "브라질 AI 발생에 따라...")
       - 알레르기 정보 (예: "알러지유발식품:", "새우젓")
       - 원산지 정보 (예: "원산지:")
       - 영양 정보나 기타 설명

    3. 특수문자 및 기호 처리:
       - 메뉴 앞의 특수문자나 번호는 제거 (예: "1.", "*", "◆")
       - "~", "&", "/" 등으로 연결된 경우 하나의 메뉴로 처리
       - 괄호 안의 설명은 제거 (예: "깍두기(새우젓)" → "깍두기")

    4. 메뉴 분리 및 정리:
       - 띄어쓰기나 구분자 없이 붙어있는 메뉴들을 적절히 분리
       - 동일한 메뉴는 한 번만 포함
       - 명확한 음식 이름만 추출
       - 소스나 토핑이 포함된 경우 전체를 하나의 메뉴로 처리

    5. 일반적인 대학교 식당 메뉴 패턴 인식:
       - 밥류: 쌀밥, 잡곡밥, 현미밥 등
       - 국/찌개류: 미역국, 된장찌개, 김치찌개 등
       - 메인요리: 불고기, 치킨까스, 부대찌개 등
       - 반찬류: 김치, 깍두기, 나물 등
       - 디저트: 요구르트, 과일 등

    예시:
    입력: "석식1 대면 코너 도담 식당 매실우불고기 도라지오이생채 잡곡밥 우묵냉국 양배추&쌈장 깍두기 알러지유발식품: 깍두기(새우젓)"
    출력: ["매실우불고기", "도라지오이생채", "잡곡밥", "우묵냉국", "양배추&쌈장", "깍두기"]

    입력: "햄듬뿍~부대볶음 미역국 쌀밥 치킨까스&허니s 망고샐러드 깍두기 요구르트"
    출력: ["햄듬뿍부대볶음", "미역국", "쌀밥", "치킨까스&허니소스", "망고샐러드", "깍두기", "요구르트"]

    입력: "1.김치찌개*쌀밥◆돈까스(소스포함)/샐러드 요구르트"
    출력: ["김치찌개", "쌀밥", "돈까스", "샐러드", "요구르트"]
    """

    GPT_MODEL: str = "gpt-4o-mini"

    @classmethod
    def from_env(cls) -> 'Settings':
        """환경 변수에서 설정을 로드합니다."""
        return cls(
            GPT_API_KEY=cls._get_required_env("GPT_API_KEY"),
            SLACK_WEBHOOK_URL=cls._get_required_env("SLACK_WEBHOOK_URL"),
            API_BASE_URL=cls._get_required_env("API_BASE_URL"),
            DEV_API_BASE_URL=cls._get_required_env("DEV_API_BASE_URL"),
            DODAM_LAMBDA_BASE_URL=cls._get_required_env("DODAM_LAMBDA_BASE_URL"),
            HAKSIK_LAMBDA_BASE_URL=cls._get_required_env("HAKSIK_LAMBDA_BASE_URL"),
            DORMITORY_LAMBDA_BASE_URL=cls._get_required_env("DORMITORY_LAMBDA_BASE_URL"),
            # FACULTY_LAMBDA_BASE_URL=cls._get_required_env("FACULTY_LAMBDA_BASE_URL"), # TODO
            FACULTY_LAMBDA_BASE_URL="",
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