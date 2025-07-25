from functions.config.settings import Settings
from functions.shared.models.menu import RestaurantType
from functions.shared.repositories.interfaces import (
    MenuScraperInterface, MenuParserInterface, APIClientInterface, NotificationClientInterface
)


class DependencyContainer:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._instances = {}

    def get_scraper(self, restaurant_type: RestaurantType) -> MenuScraperInterface:
        """식당 타입에 따른 스크래퍼 반환"""
        scraper_map = {
            RestaurantType.HAKSIK: self._create_haksik_scraper,
            RestaurantType.DODAM: self._create_dodam_scraper,
            RestaurantType.DORMITORY: self._create_dormitory_scraper,
            RestaurantType.FACULTY: self._create_faculty_scraper,
        }

        if restaurant_type not in scraper_map:
            raise ValueError(f"Unknown restaurant type: {restaurant_type}")

        return scraper_map[restaurant_type]()

    def _create_haksik_scraper(self) -> MenuScraperInterface:
        from functions.shared.repositories.scrapers.haksik_scraper import HaksikScraper
        return HaksikScraper(self._settings)

    def _create_dodam_scraper(self) -> MenuScraperInterface:
        from functions.shared.repositories.scrapers.dodam_scraper import DodamScraper
        return DodamScraper(self._settings)

    def _create_dormitory_scraper(self) -> MenuScraperInterface:
        from functions.shared.repositories.scrapers.dormitory_scraper import DormitoryScraper
        return DormitoryScraper(self._settings)

    def _create_faculty_scraper(self) -> MenuScraperInterface:
        from functions.shared.repositories.scrapers.faculty_scraper import FacultyScraper
        return FacultyScraper(self._settings)

    def get_parser(self) -> MenuParserInterface:
        """GPT 파서 반환 (싱글톤)"""
        if 'parser' not in self._instances:
            from functions.shared.repositories.clients.gpt_client import GPTClient
            self._instances['parser'] = GPTClient(self._settings.GPT_API_KEY)
        return self._instances['parser']

    def get_api_client(self, is_dev: bool = False) -> APIClientInterface:
        """Spring API 클라이언트 반환 (환경별 싱글톤)"""
        key = f'api_client_{"dev" if is_dev else "prod"}'
        if key not in self._instances:
            from functions.shared.repositories.clients.api_client import SpringAPIClient
            base_url = self._settings.DEV_API_BASE_URL if is_dev else self._settings.API_BASE_URL
            self._instances[key] = SpringAPIClient(base_url)
        return self._instances[key]

    def get_slack_client(self) -> NotificationClientInterface:
        """Slack 클라이언트 반환 (싱글톤)"""
        if 'slack_client' not in self._instances:
            from functions.shared.repositories.clients.slack_client import SlackClient
            self._instances['slack_client'] = SlackClient(self._settings.SLACK_WEBHOOK_URL)
        return self._instances['slack_client']

    def get_scraping_service(self):
        """스크래핑 서비스 반환 (의존성들을 주입받음)"""
        from functions.shared.services.scraping_service import ScrapingService
        return ScrapingService(self)

    def get_notification_service(self):
        """알림 서비스 반환"""
        from functions.shared.services.notification_service import NotificationService
        return NotificationService(self)

    def get_scheduling_service(self):
        """스케줄링 서비스 반환"""
        from functions.shared.services.scheduling_service import SchedulingService
        return SchedulingService(self)


# 전역 컨테이너 관리
_container = None


def get_container():
    """전역 DI 컨테이너 반환"""
    global _container
    if _container is None:
        from functions.config.settings import Settings
        settings = Settings.from_env()
        _container = DependencyContainer(settings)
    return _container


def set_container(container):
    """테스트용 컨테이너 설정"""
    global _container
    _container = container


def reset_container():
    """컨테이너 초기화 (주로 테스트 후 정리용)"""
    global _container
    _container = None
