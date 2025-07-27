import asyncio
import logging

import pytest

from functions.config.dependencies import get_container
from functions.shared.models.exceptions import HolidayException, MenuFetchException
from functions.shared.models.model import RestaurantType, RawMenuData
from functions.shared.repositories.scrapers.dodam_scraper import DodamScraper
from functions.shared.repositories.scrapers.dormitory_scraper import DormitoryScraper
from functions.shared.repositories.scrapers.haksik_scraper import HaksikScraper

# 테스트용 날짜들 (실제 운영했을 것 같은 날짜)
WEEKDAY_DATE = "20240325"  # 2024년 3월 25일 월요일
WEEKEND_DATE = "20240324"  # 2024년 3월 24일 일요일
HOLIDAY_DATE = "20240101"  # 2024년 1월 1일 신정


class TestDodamScraperReal:
    """도담식당 실제 스크래핑 테스트"""

    @pytest.fixture
    def scraper(self):
        return DodamScraper()

    @pytest.mark.integration
    async def test_scrape_weekday_menu(self, scraper):
        """평일 메뉴 스크래핑 테스트"""
        try:
            result = await scraper.scrape_menu(WEEKDAY_DATE)

            assert result is not None
            assert result.date == WEEKDAY_DATE
            assert result.restaurant == RestaurantType.DODAM
            assert result.menu_texts is not None
            assert len(result.menu_texts) > 0

            # 도담식당은 보통 중식, 석식이 있어야 함
            menu_keys = list(result.menu_texts.keys())
            print(f"도담식당 메뉴 슬롯들: {menu_keys}")

            # 메뉴 내용이 실제로 있는지 확인
            for slot, content in result.menu_texts.items():
                assert content is not None
                assert len(content.strip()) > 0
                print(f"{slot}: {content[:50]}...")

        except HolidayException as e:
            pytest.skip(f"해당 날짜는 휴무일입니다: {e}")
        except MenuFetchException as e:
            pytest.fail(f"메뉴 조회 실패: {e}")

    @pytest.mark.integration
    async def test_scrape_holiday_or_weekend(self, scraper):
        """휴일/주말 스크래핑 테스트"""
        try:
            result = await scraper.scrape_menu(HOLIDAY_DATE)
            # 휴무일이면 HolidayException이 발생해야 함
            pytest.fail("휴무일인데 예외가 발생하지 않았습니다")
        except HolidayException:
            # 정상적인 휴무일 처리
            assert True
        except MenuFetchException:
            # 메뉴가 없는 경우도 정상
            assert True


class TestHaksikScraperReal:
    """학생식당 실제 스크래핑 테스트"""

    @pytest.fixture
    def scraper(self):
        return HaksikScraper()

    @pytest.mark.integration
    async def test_scrape_weekday_menu(self, scraper):
        """평일 메뉴 스크래핑 테스트"""
        try:
            result = await scraper.scrape_menu(WEEKDAY_DATE)

            assert result is not None
            assert result.date == WEEKDAY_DATE
            assert result.restaurant == RestaurantType.HAKSIK
            assert result.menu_texts is not None

            # 학생식당 메뉴 확인
            menu_keys = list(result.menu_texts.keys())
            print(f"학생식당 메뉴 슬롯들: {menu_keys}")

            for slot, content in result.menu_texts.items():
                assert content is not None
                assert len(content.strip()) > 0
                print(f"{slot}: {content[:50]}...")

        except HolidayException as e:
            pytest.skip(f"해당 날짜는 휴무일입니다: {e}")
        except MenuFetchException as e:
            pytest.fail(f"메뉴 조회 실패: {e}")


class TestFacultyScraperReal:
    """교직원식당 실제 스크래핑 테스트"""

    @pytest.fixture
    def scraper(self):
        return FacultyScraper()

    @pytest.mark.integration
    async def test_scrape_weekday_menu(self, scraper):
        """평일 메뉴 스크래핑 테스트"""
        try:
            result = await scraper.scrape_menu(WEEKDAY_DATE)

            assert result is not None
            assert result.date == WEEKDAY_DATE
            assert result.restaurant == RestaurantType.FACULTY
            assert result.menu_texts is not None

            # 교직원식당은 보통 점심만 있음
            menu_keys = list(result.menu_texts.keys())
            print(f"교직원식당 메뉴 슬롯들: {menu_keys}")

            for slot, content in result.menu_texts.items():
                assert content is not None
                assert len(content.strip()) > 0
                print(f"{slot}: {content[:50]}...")

        except HolidayException as e:
            pytest.skip(f"해당 날짜는 휴무일입니다: {e}")
        except MenuFetchException as e:
            pytest.fail(f"메뉴 조회 실패: {e}")


class TestDormitoryScraperReal:
    """기숙사식당 실제 스크래핑 테스트"""

    @pytest.fixture
    def scraper(self):
        return DormitoryScraper()

    @pytest.mark.integration
    async def test_scrape_weekday_menu(self, scraper):
        """평일 메뉴 스크래핑 테스트"""
        try:
            result = await scraper.scrape_menu(WEEKDAY_DATE)

            assert result is not None
            assert result.date == WEEKDAY_DATE
            assert result.restaurant == RestaurantType.DORMITORY
            assert result.menu_texts is not None

            # 기숙사식당 메뉴 확인
            menu_keys = list(result.menu_texts.keys())
            print(f"기숙사식당 메뉴 슬롯들: {menu_keys}")

            # 기숙사는 중식, 석식만 있어야 함 (조식 운영 안함)
            assert "조식" not in menu_keys

            for slot, content in result.menu_texts.items():
                assert content is not None
                assert len(content.strip()) > 0
                print(f"{slot}: {content[:50]}...")

        except HolidayException as e:
            pytest.skip(f"해당 날짜는 휴무일입니다: {e}")
        except MenuFetchException as e:
            pytest.fail(f"메뉴 조회 실패: {e}")


class TestScraperNetworkIssues:
    """스크래퍼 네트워크 문제 테스트"""

    @pytest.mark.integration
    async def test_invalid_date_format(self):
        """잘못된 날짜 형식 테스트"""
        scraper = DodamScraper()

        with pytest.raises(Exception):  # 적절한 예외가 발생해야 함
            await scraper.scrape_menu("invalid-date")

    @pytest.mark.integration
    async def test_future_date(self):
        """미래 날짜 테스트"""
        scraper = DodamScraper()
        future_date = "20301225"  # 먼 미래

        try:
            result = await scraper.scrape_menu(future_date)
            # 메뉴가 없거나 휴무일 처리되어야 함
            if result:
                assert result.date == future_date
        except (HolidayException, MenuFetchException):
            # 정상적인 예외 처리
            assert True

    @pytest.mark.integration
    async def test_very_old_date(self):
        """과거 날짜 테스트"""
        scraper = DodamScraper()
        old_date = "20200101"  # 코로나 시기

        try:
            result = await scraper.scrape_menu(old_date)
            if result:
                assert result.date == old_date
        except (HolidayException, MenuFetchException):
            # 과거 데이터는 없을 수 있음
            assert True


class TestAllScrapersComparison:
    """모든 스크래퍼 비교 테스트"""

    @pytest.mark.integration
    async def test_all_scrapers_same_date(self):
        """같은 날짜로 모든 스크래퍼 테스트"""
        scrapers = [
            (DodamScraper(), "도담식당"),
            (HaksikScraper(), "학생식당"),
            (FacultyScraper(), "교직원식당"),
            (DormitoryScraper(), "기숙사식당")
        ]

        results = {}

        for scraper, name in scrapers:
            try:
                result = await scraper.scrape_menu(WEEKDAY_DATE)
                results[name] = {
                    'success': True,
                    'menu_count': len(result.menu_texts) if result.menu_texts else 0,
                    'slots': list(result.menu_texts.keys()) if result.menu_texts else []
                }
                print(f"{name}: {results[name]}")

            except (HolidayException, MenuFetchException) as e:
                results[name] = {
                    'success': False,
                    'error': str(e)
                }
                print(f"{name}: 실패 - {e}")

        # 최소 하나는 성공해야 함
        success_count = sum(1 for r in results.values() if r['success'])
        assert success_count > 0, "모든 스크래퍼가 실패했습니다"

        print(f"\n성공한 스크래퍼: {success_count}/4")


# 실행 가이드 주석
"""
실제 스크래퍼 테스트 실행 방법:

# 모든 실제 스크래퍼 테스트
uv run pytest tests/test_scrapers_real.py -v -m integration

# 특정 스크래퍼만
uv run pytest tests/test_scrapers_real.py::TestDodamScraperReal -v -m integration

# 모든 스크래퍼 비교 테스트
uv run pytest tests/test_scrapers_real.py::TestAllScrapersComparison::test_all_scrapers_same_date -v -s

주의사항:
- 실제 웹사이트에 요청하므로 인터넷 연결 필요
- 웹사이트 점검시간이나 서버 문제로 실패할 수 있음
- 휴무일에는 HolidayException 발생이 정상
- 메뉴가 없는 날에는 MenuFetchException 발생이 정상
"""

if __name__ == '__main__':
    date = "20240325"
    container = get_container()
    scraping_service = container.get_scraping_service()
    logging.basicConfig(level=logging.INFO)

    # dodam_parsed_menu: ParsedMenuData = asyncio.run(scraping_service.scrape_and_process(date, RestaurantType.DODAM))
    from functions.shared.repositories.scrapers.faculty_scraper import FacultyScraper
    haksik_parsed_menu: RawMenuData = asyncio.run(HaksikScraper().scrape_menu(date=date))

    faculty_parsed_menu: RawMenuData = asyncio.run(FacultyScraper().scrape_menu(date=date))
    # haksik_parsed_menu = asyncio.run(scraping_service.scrape_and_process(date, RestaurantType.HAKSIK))
    # dorm_parsed_menu = asyncio.run(scraping_service.scrape_and_process(date, RestaurantType.DORMITORY))



