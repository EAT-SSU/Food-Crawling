from functions.config.settings import Settings
from functions.shared.models.menu import RestaurantType


class DependencyContainer:
    """DI Container"""

    def __init__(self, settings: Settings):
        self._settings = settings

    def get_scraper(self, restaurant_type: RestaurantType):
        """스크래퍼 생성"""
        factory_map = {
            RestaurantType.HAKSIK: self._create_haksik_scraper,
            RestaurantType.DODAM: self._create_dodam_scraper,
            RestaurantType.DORMITORY: self._create_dormitory_scraper,
            RestaurantType.FACULTY: self._create_faculty_scraper,
        }

        if restaurant_type not in factory_map:
            raise ValueError(f"Unknown restaurant type: {restaurant_type}")

        return factory_map[restaurant_type]()

    def get_parser(self):
        """GPT 클라이언트 생성"""
        from functions.shared.repositories.clients.gpt_client import GPTClient
        return GPTClient(self._settings.GPT_API_KEY)

    def get_prod_api_client(self):
        """프로덕션 API 클라이언트 생성"""
        from functions.shared.repositories.clients.spring_api_client import SpringAPIClient
        return SpringAPIClient(self._settings.API_BASE_URL)

    def get_dev_api_client(self):
        """개발 API 클라이언트 생성"""
        from functions.shared.repositories.clients.spring_api_client import SpringAPIClient
        return SpringAPIClient(self._settings.DEV_API_BASE_URL)

    def get_slack_client(self):
        """Slack 클라이언트 생성"""
        from functions.shared.repositories.clients.slack_client import SlackClient
        return SlackClient(self._settings.SLACK_WEBHOOK_URL)

    def get_scraping_service(self):
        """스크래핑 서비스 생성"""
        from functions.shared.services.scraping_service import ScrapingService
        return ScrapingService(self)

    def get_notification_service(self):
        """알림 서비스 생성"""
        from functions.shared.services.notification_service import NotificationService
        return NotificationService(self)

    def get_scheduling_service(self):
        """스케줄링 서비스 생성"""
        from functions.shared.services.scheduling_service import SchedulingService
        return SchedulingService(self)

    # Private factory methods
    def _create_haksik_scraper(self):
        from functions.shared.repositories.scrapers.haksik_scraper import HaksikScraper
        return HaksikScraper(self._settings)

    def _create_dodam_scraper(self):
        from functions.shared.repositories.scrapers.dodam_scraper import DodamScraper
        return DodamScraper(self._settings)

    def _create_dormitory_scraper(self):
        from functions.shared.repositories.scrapers.dormitory_scraper import DormitoryScraper
        return DormitoryScraper(self._settings)

    def _create_faculty_scraper(self):
        from functions.shared.repositories.scrapers.faculty_scraper import FacultyScraper
        return FacultyScraper(self._settings)


# 전역 컨테이너 관리
_container = None


def get_container() -> DependencyContainer:
    """전역 DI 컨테이너 반환"""
    global _container
    if _container is None:
        from functions.config.settings import Settings
        settings = Settings.from_env()
        _container = DependencyContainer(settings)
    return _container


def reset_container():
    """테스트용 컨테이너 초기화"""
    global _container
    _container = None
