import os

import pytest

from functions.config.dependencies import get_container, reset_container
from functions.shared.models.model import RestaurantType


@pytest.fixture(scope="module", autouse=True)
def setup_test_env():
    """테스트용 환경변수 설정"""
    test_vars = {
        'GPT_API_KEY': 'test-key',
        'SLACK_WEBHOOK_URL': 'https://test.com',
        'API_BASE_URL': 'https://api.test.com',
        'DEV_API_BASE_URL': 'https://dev.test.com',
        'DODAM_LAMBDA_BASE_URL': 'https://dodam.test.com',
        'HAKSIK_LAMBDA_BASE_URL': 'https://haksik.test.com',
        'DORMITORY_LAMBDA_BASE_URL': 'https://dorm.test.com',
        'FACULTY_LAMBDA_BASE_URL': 'https://faculty.test.com'
    }

    # 백업
    backup = {k: os.environ.get(k) for k in test_vars}

    # 설정
    for k, v in test_vars.items():
        os.environ[k] = v

    yield

    # 복원
    for k, v in backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestDependencyContainer:
    """DI 컨테이너 기본 테스트"""

    def test_scrapers_not_none(self):
        """모든 스크래퍼가 None이 아닌지 테스트"""
        reset_container()
        container = get_container()

        assert container.get_scraper(RestaurantType.DODAM) is not None
        assert container.get_scraper(RestaurantType.HAKSIK) is not None
        assert container.get_scraper(RestaurantType.FACULTY) is not None
        assert container.get_scraper(RestaurantType.DORMITORY) is not None

    def test_clients_not_none(self):
        """모든 클라이언트가 None이 아닌지 테스트"""
        reset_container()
        container = get_container()

        assert container.get_parser() is not None
        assert container.get_prod_api_client() is not None
        assert container.get_dev_api_client() is not None
        assert container.get_slack_client() is not None

    def test_services_not_none(self):
        """모든 서비스가 None이 아닌지 테스트"""
        reset_container()
        container = get_container()

        assert container.get_scraping_service() is not None
        assert container.get_notification_service() is not None
        assert container.get_scheduling_service() is not None

    def test_container_singleton(self):
        """컨테이너 싱글톤 테스트"""
        reset_container()

        container1 = get_container()
        container2 = get_container()

        assert container1 is container2

    def test_invalid_scraper_type(self):
        """잘못된 스크래퍼 타입 테스트"""
        reset_container()
        container = get_container()

        with pytest.raises(ValueError):
            container.get_scraper("INVALID_TYPE")