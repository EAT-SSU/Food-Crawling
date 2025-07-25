import json
import logging
import re

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.config.settings import Settings
from functions.shared.models.model import RawMenuData, ParsedMenuData
from functions.shared.repositories.interfaces import MenuParserInterface

logger = logging.getLogger(__name__)


class GPTClient(MenuParserInterface):
    """OpenAI GPT API 클라이언트"""

    def __init__(self, api_key: str, model: str = None, function_tools: list = None, system_prompt: str = None):
        self.client = AsyncOpenAI(api_key=api_key)

        # Settings에서 기본값 가져오기
        if model is None or function_tools is None or system_prompt is None:
            from functions.config.settings import get_settings
            settings:Settings = get_settings()

        self.model = model or settings.GPT_MODEL
        self.function_tools = function_tools or settings.GPT_FUNCTION_TOOLS
        self.system_prompt = system_prompt or settings.GPT_SYSTEM_PROMPT

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    async def parse_menu(self, raw_menu: RawMenuData) -> ParsedMenuData:
        """GPT를 사용하여 메뉴 텍스트에서 모든 메뉴를 추출합니다."""
        logger.info(f"GPT 메뉴 파싱 시작: {raw_menu.restaurant.korean_name} {raw_menu.date}")

        result_dict = {}
        errors = {}

        for key, value in raw_menu.menu_texts.items():
            try:
                logger.debug(f"메뉴 슬롯 처리 중: {key}")

                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": f"다음 식당 메뉴 텍스트에서 실제 음식 메뉴만 추출해주세요:\n\n{value}"}
                    ],
                    tools=self.function_tools,
                    tool_choice={"type": "function", "function": {"name": "extract_all_menus"}}
                )

                # 함수 호출 결과 파싱
                tool_call = response.choices[0].message.tool_calls[0]
                function_args = json.loads(tool_call.function.arguments)
                menus = function_args.get("all_menus", [])  # 키명 업데이트

                # 빈 결과 확인
                if not menus:
                    logger.warning(f"메뉴 슬롯 '{key}'에서 메뉴를 찾지 못했습니다.")
                    errors[key] = "메뉴를 찾지 못했습니다."

                # 특수문자 제거
                refined_menus = [re.sub(r'[\*]+(?=[\uAC00-\uD7A3])', '', menu) for menu in menus]
                result_dict[key] = refined_menus

            except Exception as e:
                logger.error(f"메뉴 슬롯 '{key}' 처리 중 오류 발생: {str(e)}")
                errors[key] = str(e)

        # 성공 여부 확인
        is_successful = len(errors) == 0

        parsed_menu_data = ParsedMenuData(
            date=raw_menu.date,
            restaurant=raw_menu.restaurant,
            menus=result_dict,
            error_slots=errors,
            success=len(errors) == 0  # success 필드 추가
        )

        if is_successful:
            logger.info(f"GPT 메뉴 파싱 성공: {raw_menu.restaurant.korean_name} {raw_menu.date}")
        else:
            error_slots = ", ".join(errors.keys())
            logger.warning(f"GPT 메뉴 파싱 부분 실패: {raw_menu.restaurant.korean_name} {raw_menu.date} (실패 슬롯: {error_slots})")

        return parsed_menu_data