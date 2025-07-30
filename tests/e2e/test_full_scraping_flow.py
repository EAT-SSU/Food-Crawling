import asyncio
import os

import pytest

from functions.config.dependencies import get_container, reset_container
from functions.shared.models.model import RestaurantType, ParsedMenuData
from functions.shared.services.scraping_service import ScrapingService


# E2E 테스트는 실제 외부 서비스에 영향을 주므로, 특별한 마커를 사용합니다.
# 실행 명령어: pytest -m e2e
@pytest.mark.e2e
class TestFullScrapingFlow:
    """
    End-to-End 테스트: 전체 스크래핑 및 처리 플로우를 검증합니다.

    이 테스트를 실행하기 전, 다음 환경변수가 설정되어야 합니다:
    - GPT_API_KEY: 실제 OpenAI API 키
    - API_BASE_URL: 실제 운영 Spring API 서버 URL
    - DEV_API_BASE_URL: 실제 개발 Spring API 서버 URL
    - SLACK_WEBHOOK_URL: (선택 사항) 테스트용 Slack 웹훅 URL
    """

    @pytest.fixture(scope="class", autouse=True)
    def check_env_vars(self):
        """E2E 테스트에 필요한 환경변수가 설정되었는지 확인합니다."""
        required_vars = ["GPT_API_KEY", "API_BASE_URL", "DEV_API_BASE_URL"]
        if not all(os.getenv(var) for var in required_vars):
            pytest.skip("E2E 테스트를 위한 환경변수가 설정되지 않았습니다.")

    @pytest.fixture(scope="class")
    def event_loop(self):
        """클래스 스코프의 이벤트 루프를 제공합니다."""
        loop = asyncio.get_event_loop_policy().new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture(scope="class")
    def scraping_service(self) -> ScrapingService:
        """실제 의존성을 주입받은 ScrapingService 인스턴스를 반환합니다."""
        # reset_container()를 통해 이전에 Mock된 의존성이 없도록 보장합니다.
        reset_container()
        container = get_container()
        return container.get_scraping_service()

    @pytest.mark.asyncio
    async def test_dodam_e2e(self, scraping_service: ScrapingService):
        """도담식당 E2E 테스트 (평일)"""
        # 실제 메뉴가 있을 법한 과거의 특정 평일 날짜
        target_date = "20240325"
        restaurant = RestaurantType.DODAM

        try:
            # is_dev=True로 설정하여 개발 API 서버에만 데이터를 전송합니다.
            result: ParsedMenuData = await scraping_service.scrape_and_process(
                date=target_date,
                restaurant_type=restaurant,
                is_dev=True
            )

            # 검증
            assert result.success is True, f"파싱 실패 슬롯: {result.error_slots}"
            assert result.date == target_date
            assert result.restaurant == restaurant

            # 성공적으로 파싱된 메뉴가 하나 이상 있어야 함
            successful_slots = result.get_successful_slots()
            assert len(successful_slots) > 0, "성공적으로 파싱된 메뉴가 없습니다."

            # 기대값 정의
            expected_menus = {
                '중식1': ['뼈없는닭갈비', '크레잇고기왕교자만두찜', '부추콩나물무침', '찰흑미밥', '우거지국', '깍두기', '야쿠르트'],
                '중식4': ['샐러드비빔밥', '계란후라이', '우거지국', '포기김치', '야쿠르트'],
                '석식1': ['제육볶음', '오징어청경채무침', '상추&쌈장', '잡곡밥', '북어국', '포기김치', '야쿠르트']
            }

            # 각 슬롯별 set 비교 (순서 무관)
            menus = result.menus
            for slot, expected_items in expected_menus.items():
                assert slot in menus, f"슬롯 '{slot}'이 결과에 없습니다"
                actual_items = menus[slot]

                print(f"\n슬롯 '{slot}' 비교:")
                print(f"  기대: {sorted(expected_items)}")
                print(f"  실제: {sorted(actual_items)}")

                # 순서 무관 비교
                assert set(expected_items) == set(actual_items), f"""
                    슬롯 '{slot}' 메뉴 불일치 (순서 무관):
                    기대: {sorted(expected_items)}
                    실제: {sorted(actual_items)}
                    누락: {sorted(set(expected_items) - set(actual_items))}
                    추가: {sorted(set(actual_items) - set(expected_items))}"""


            print(f"\n[E2E 테스트 성공] {restaurant.korean_name} ({target_date}) - 모든 메뉴 일치! (순서 무관)")

        except Exception as e:
            pytest.fail(f"E2E 테스트 중 예외 발생: {e}")

    @pytest.mark.asyncio
    async def test_haksik_e2e(self, scraping_service: ScrapingService):
        """학생식당 E2E 테스트 (평일) - 기대값 검증 포함"""
        target_date = "20240325"
        restaurant = RestaurantType.HAKSIK

        try:
            result: ParsedMenuData = await scraping_service.scrape_and_process(
                date=target_date,
                restaurant_type=restaurant,
                is_dev=True
            )

            # 기본 검증
            assert result.success is True, f"파싱 실패 슬롯: {result.error_slots}"
            assert result.date == target_date
            assert result.restaurant == restaurant

            # 성공적으로 파싱된 메뉴가 하나 이상 있어야 함
            successful_slots = result.get_successful_slots()
            assert len(successful_slots) > 0, "성공적으로 파싱된 메뉴가 없습니다."

            # 실제 출력 확인을 위한 print
            print(f"\n[학생식당 실제 파싱 결과] ({target_date})")
            print(f"전체 메뉴: {result.menus}")

            # 기대값과 비교 검증
            expected_menus = {
                "중식1": ["꼬치어묵우동", "칠리탕수육", "미니밥", "단무지"],
                "중식2": ["고추장불고기덮밥&계란후라이", "우동국물", "칠리탕수육", "맛김치"],
                "중식3": ["함박스테이크&파인애플볶음밥", "만다린샐러드", "우동국물", "단무지"],
                "석식1": ["닭살데리야끼볶음", "얼큰콩나물국", "새송이버섯볶음", "아삭이고추된장무침", "도시락김", "맛김치", "찰흑미밥"]
            }

            # 각 슬롯별 set 비교 (순서 무관)
            menus = result.menus
            for expected_slot, expected_items in expected_menus.items():
                assert expected_slot in menus, f"슬롯 '{expected_slot}'이 결과에 없습니다"
                actual_items = menus[expected_slot]

                print(f"\n슬롯 '{expected_slot}' 비교:")
                print(f"  기대: {sorted(expected_items)}")
                print(f"  실제: {sorted(actual_items)}")

                assert set(expected_items) == set(actual_items), f"""
                    슬롯 '{expected_slot}' 메뉴 불일치 (순서 무관):
                    기대: {sorted(expected_items)}
                    실제: {sorted(actual_items)}
                    누락: {sorted(set(expected_items) - set(actual_items))}
                    추가: {sorted(set(actual_items) - set(expected_items))}"""

            print(f"\n[E2E 테스트 성공] {restaurant.korean_name} ({target_date}) - 모든 기대값과 일치! (순서 무관)")

        except AssertionError:
            # AssertionError는 재발생시켜서 테스트 실패로 처리
            raise
        except Exception as e:
            pytest.fail(f"E2E 테스트 중 예외 발생: {e}")

    @pytest.mark.asyncio
    async def test_faculty_e2e(self, scraping_service: ScrapingService):
        """교직원식당 E2E 테스트 (평일)"""
        target_date = "20240325"
        restaurant = RestaurantType.FACULTY

        try:

            result = await scraping_service.scrape_and_process(date=target_date,restaurant_type=restaurant,is_dev=True)

            # 검증
            assert result.success is True, f"파싱 실패 슬롯: {result.error_slots}"
            assert result.date == target_date
            assert result.restaurant == restaurant

            # 성공적으로 파싱된 메뉴가 하나 이상 있어야 함
            successful_slots = result.get_successful_slots()
            assert len(successful_slots) > 0, "성공적으로 파싱된 메뉴가 없습니다."

            # 교직원식당 기대값 정의 (점심만 운영)
            expected_menus = {
                '중식1': ['안동찜닭', '뚝배기차돌순두부찌개', '부들어묵볶음', '유자부추무침', '포기김치', '보리차', '쌀밥', '당근사과주스']
            }

            # 각 슬롯별 set 비교 (순서 무관)
            menus = result.menus
            for slot, expected_items in expected_menus.items():
                if slot in menus:  # 해당 슬롯이 있는 경우에만 검증
                    actual_items = menus[slot]

                    print(f"\n슬롯 '{slot}' 비교:")
                    print(f"  기대: {sorted(expected_items)}")
                    print(f"  실제: {sorted(actual_items)}")
                    assert set(expected_items) == set(actual_items), f"""
                    슬롯 '{slot}' 메뉴 불일치 (순서 무관):
                    기대: {sorted(expected_items)}
                    실제: {sorted(actual_items)}
                    누락: {sorted(set(expected_items) - set(actual_items))}
                    추가: {sorted(set(actual_items) - set(expected_items))}
                    """

            print(f"\n[E2E 테스트 성공] {restaurant.korean_name} ({target_date}) - 메뉴 파싱 완료!")

        except Exception as e:
            pytest.fail(f"E2E 테스트 중 예외 발생: {e}")

    @pytest.mark.asyncio
    async def test_dormitory_e2e(self, scraping_service: ScrapingService):
        """기숙사식당 E2E 테스트 (주간 메뉴)"""
        target_date = "20240325"
        restaurant = RestaurantType.DORMITORY

        try:
            # is_dev=True로 설정하여 개발 API 서버에만 데이터를 전송합니다.
            result: ParsedMenuData = await scraping_service.scrape_menu(
                date=target_date,
                restaurant_type=restaurant
            )
            # 검증
            assert result.success is True, f"파싱 실패 슬롯: {result.error_slots}"
            assert result.date == target_date
            assert result.restaurant == restaurant

            # 성공적으로 파싱된 메뉴가 하나 이상 있어야 함
            successful_slots = result.get_successful_slots()
            assert len(successful_slots) > 0, "성공적으로 파싱된 메뉴가 없습니다."

            # 기숙사식당 주간 메뉴 샘플 검증 (첫 번째 날)
            if result.date == "20240326":
                expected_first_day_menus = {
                    "중식": ['사골미역국', '쌀밥&흑미밥', '큐브목살김치찜', '왕찐만두&양념장', '콩나물무침', '구이김', '요구르트'],
                    "석식": ['까르보나라스파게티', '미소장국', '쌀밥', '사천식치킨까스', '오리엔탈그린샐러드', '배추김치', '요구르트']
                }

                for slot, expected_items in expected_first_day_menus.items():
                    if slot in result.menus:
                        actual_items = result.menus[slot]
                        print(f"\n기숙사 {result.date} '{slot}' 비교:")
                        print(f"  기대: {sorted(expected_items)}")
                        print(f"  실제: {sorted(actual_items)}")

                        assert set(expected_items) == set(actual_items), f"""
                        기숙사 {result.date} '{slot}' 메뉴 불일치:
                        기대: {sorted(expected_items)}
                        실제: {sorted(actual_items)}
                        """

            print(f"\n[E2E 테스트 성공] {restaurant.korean_name} 주간 메뉴 ({result}일치) - 파싱 완료!")

        except Exception as e:
            pytest.fail(f"기숙사식당 E2E 테스트 중 예외 발생: {e}")

# 실행 가이드:
# 1. 필요한 환경변수 설정 (GPT_API_KEY, API_BASE_URL, DEV_API_BASE_URL)
#    export GPT_API_KEY="sk-..."
#    export API_BASE_URL="https://..."
#    export DEV_API_BASE_URL="https://..."
#
# 2. pytest 실행 (e2e 마커 사용)
#    uv run pytest -m e2e -v -s
#
# 3. 학생식당만 테스트하려면:
#    uv run pytest -m e2e -k "haksik" -v -s
#
#    (-s 옵션을 주면 print 출력을 볼 수 있습니다.)
