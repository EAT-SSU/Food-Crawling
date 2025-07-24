import os

import openai

# Secret env
ENCRYPTED = os.environ['GPT_API_KEY']
openai.api_key = ENCRYPTED
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
API_BASE_URL = os.getenv("API_BASE_URL")
DEV_API_BASE_URL = os.getenv("DEV_API_BASE_URL")

# AWS lambda base url
DODAM_LAMBDA_BASE_URL = os.getenv("DODAM_LAMBDA_BASE_URL")
HAKSIK_LAMBDA_BASE_URL = os.getenv("HAKSIK_LAMBDA_BASE_URL")
FACULTY_LAMBDA_BASE_URL = os.getenv("FACULTY_LAMBDA_BASE_URL")
DORMITORY_LAMBDA_BASE_URL = os.getenv("DORMITORY_LAMBDA_BASE_URL")

# 숭실대 생협의 api에서 쓰는 구분자
SOONGGURI_HAKSIK_RCD = 1
SOONGGURI_DODAM_RCD = 2
SOONGGURI_FACULTY_RCD = 7


# 도담식당(점심, 저녁), 학생식당(1000원 조식, 점심), 기숙사식당(아침,점심,저녁)
DODAM_LUNCH_PRICE = 6000
DODAM_DINNER_PRICE = 6000

HAKSIK_ONE_DOLLOR_MORNING_PRICE = 1000
HAKSIK_MORNING_PRICE = 1000
HAKSIK_LUNCH_PRICE = 5000
HAKSIK_DINNER_PRICE = 5000

FACULTY_LUNCH_PRICE = 7000

DORMITORY_MORING_PRICE = 5500
DORMITORY_LUNCH_PRICE = 5500
DORMITORY_DINNER_PRICE = 5500


GPT_FUNCTION_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "extract_all_menus",
                "description": "모든 메뉴를 추출하여 리스트로 반환",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "all_menus": {
                            "type": "array",
                            "description": "모든 메뉴 목록 (중복 제거, 특수문자 제외)",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["all_menus"]
                }
            }
        }
    ]

GPT_SYSTEM_PROMPT = """
    당신은 메뉴 분류 전문가입니다. 주어진 메뉴 목록에서 모든 메뉴를 추출합니다.
    메뉴 추출 규칙:
    1. 동일한 메인 메뉴는 한 번만 포함
    2. 메뉴 앞의 특수문자는 제외
    """

GPT_MODEL = "gpt-4o-mini"

MENU_EXAMPLE = """
"""







