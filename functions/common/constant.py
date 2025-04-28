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
DORMITORY_LAMBDA_BASE_URL = os.getenv("DORMITORY_LAMBDA_BASE_URL")

# 숭실대 생협의 api에서 쓰는 구분자
SOONGGURI_HAKSIK_RCD = 1
SOONGGURI_DODAM_RCD = 2


# 도담식당(점심, 저녁), 학생식당(1000원 조식, 점심), 기숙사식당(아침,점심,저녁)
DODAM_LUNCH_PRICE = 6000
DODAM_DINNER_PRICE = 6000

HAKSIK_ONE_DOLLOR_MORNING_PRICE = 1000
HAKSIK_MORNING_PRICE = 1000
HAKSIK_LUNCH_PRICE = 5000
HAKSIK_DINNER_PRICE = 5000

DORMITORY_MORING_PRICE = 5500
DORMITORY_LUNCH_PRICE = 5500
DORMITORY_DINNER_PRICE = 5500

GPT_FUNCTION_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "extract_main_menus",
                "description": "메인메뉴만 추출하여 리스트로 반환",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "main_menus": {
                            "type": "array",
                            "description": "메인 메뉴 목록 (중복 제거, 특수문자 제외)",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["main_menus"]
                }
            }
        }
    ]

GPT_SYSTEM_PROMPT = """
    당신은 메뉴 분류 전문가입니다. 주어진 메뉴 목록에서 메인 메뉴만 추출하고 사이드 메뉴는 제외해야 합니다.
    메인 메뉴 추출 규칙:
    1. 동일한 메인 메뉴는 한 번만 포함
    2. 메뉴 앞의 특수문자는 제외
    3. 오직 메인 메뉴만 추출 (밥, 국, 찌개, 고기류, 생선류, 메인 요리 등)
    4. 사이드 메뉴 제외 (김치, 반찬, 샐러드, 소스 등)
    """

GPT_MODEL = "gpt-4o-mini"







