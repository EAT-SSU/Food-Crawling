# Food Scrapper 리팩토링 설계서

## 1. 프로젝트 구조 개선

### 기존 구조 → 새로운 구조
```
기존:
functions/
├── common/
├── scrapping/
└── schedule/

새로운:
functions/
├── config/
├── shared/
├── scraping/
└── scheduling/
```

### 파일 이동 계획
| 기존 파일 | 새 위치 | 변경사항 |
|----------|--------|----------|
| `common/models.py` | `shared/models/` | 파일 분할 |
| `common/utils.py` | `shared/utils/` | 파일 분할 |
| `common/constant.py` | `config/settings.py` | DRF 스타일 |
| `common/exceptions.py` | `shared/models/exceptions.py` | 이동 |
| `scrapping/get_*.py` | `scraping/get_*.py` | 이동 + 리팩토링 |
| `schedule/schedule_*.py` | `scheduling/schedule_*.py` | 이동 + 리팩토링 |

## 2. SOLID 원칙 적용 설계

### S - Single Responsibility Principle (단일 책임 원칙)

#### 기존 문제점:
```python
# get_dodam.py - 여러 책임이 혼재
def lambda_handler(event, context):
    # 1. 파라미터 추출
    # 2. 웹 스크래핑
    # 3. GPT 파싱
    # 4. API 전송
    # 5. 에러 처리
    # 6. 응답 생성
```

#### 개선 후:
```python
# scraping/get_dodam.py - Lambda 핸들러만 담당
def lambda_handler(event, context):
    view = ScrapingView(RestaurantType.DODAM)
    return asyncio.run(view.handle(event, context))

# scraping/views/scraping_views.py - 요청/응답 처리만 담당
class ScrapingView:
    def handle(self, event, context): pass

# shared/services/scraping_service.py - 비즈니스 로직만 담당
class ScrapingService:
    def scrape_and_process(self, date, restaurant_type): pass

# shared/repositories/scrapers/dodam_scraper.py - 스크래핑만 담당
class DodamScraper:
    def scrape_menu(self, date): pass
```

### O - Open/Closed Principle (개방/폐쇄 원칙)

#### 기존 문제점:
```python
# 새로운 식당 추가 시 기존 코드 수정 필요
def post_dodam_menus(parsed_menu_data):
    for restrant_meal_time, menus in menu.items():
        if "중식" in restrant_meal_time:
            post_dodam_lunch(date, menus)
        elif "석식" in restrant_meal_time:
            post_dodam_dinner(date, menus)
        else:
            raise WeirdRestaurantName(...)  # 예외 발생
```

#### 개선 후:
```python
# shared/repositories/interfaces.py - 인터페이스 정의
class MenuScraperInterface(ABC):
    @abstractmethod
    def scrape_menu(self, date: str) -> RawMenuData: pass

class MenuProcessorInterface(ABC):
    @abstractmethod
    def process_menu(self, parsed_menu: ParsedMenuData) -> bool: pass

# 새 식당 추가 시 인터페이스만 구현하면 됨
class NewRestaurantScraper(MenuScraperInterface):
    def scrape_menu(self, date: str) -> RawMenuData:
        # 새 식당 구현
        pass
```

### L - Liskov Substitution Principle (리스코프 치환 원칙)

#### 설계:
```python
# 모든 스크래퍼는 동일한 인터페이스 구현
scrapers = {
    RestaurantType.HAKSIK: HaksikScraper(),
    RestaurantType.DODAM: DodamScraper(),
    RestaurantType.DORMITORY: DormitoryScraper(),
}

# 어떤 스크래퍼든 동일하게 사용 가능
scraper = scrapers[restaurant_type]
result = scraper.scrape_menu(date)  # 모든 스크래퍼에서 동일한 결과 타입 보장
```

### I - Interface Segregation Principle (인터페이스 분리 원칙)

#### 기존 문제점:
```python
# 하나의 큰 인터페이스에 모든 기능 포함
class MenuHandlerInterface:
    def scrape_menu(self): pass
    def parse_menu(self): pass
    def send_to_api(self): pass
    def send_notification(self): pass
```

#### 개선 후:
```python
# 역할별로 인터페이스 분리
class MenuScraperInterface(ABC):
    def scrape_menu(self, date: str) -> RawMenuData: pass

class MenuParserInterface(ABC):
    def parse_menu(self, raw_menu: RawMenuData) -> ParsedMenuData: pass

class APIClientInterface(ABC):
    def post_menu(self, data) -> bool: pass

class NotificationClientInterface(ABC):
    def send_notification(self, message: str) -> bool: pass
```

### D - Dependency Inversion Principle (의존성 역전 원칙)

#### 기존 문제점:
```python
# 직접적인 의존성
def fetch_and_refine_dodam(date: str):
    response = get_dodam_from_soongguri(date)  # 하드코딩된 의존성
    parsed_menu = extract_all_dishes_gpt(raw_menu)  # 직접 호출
```

#### 개선 후:
```python
# 의존성 주입을 통한 역전
class ScrapingService:
    def __init__(self, 
                 scraper: MenuScraperInterface,
                 parser: MenuParserInterface,
                 api_client: APIClientInterface):
        self._scraper = scraper
        self._parser = parser
        self._api_client = api_client
    
    async def scrape_and_process(self, date: str, restaurant_type: RestaurantType):
        raw_menu = await self._scraper.scrape_menu(date)
        parsed_menu = await self._parser.parse_menu(raw_menu)
        await self._api_client.post_menu(parsed_menu)
        return parsed_menu
```

## 3. 의존성 주입 구현

### DI Container 설계
```python
# config/dependencies.py
class DependencyContainer:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._instances = {}
    
    def get_scraper(self, restaurant_type: RestaurantType) -> MenuScraperInterface:
        scraper_factory = {
            RestaurantType.HAKSIK: lambda: HaksikScraper(),
            RestaurantType.DODAM: lambda: DodamScraper(),
            RestaurantType.DORMITORY: lambda: DormitoryScraper(),
            RestaurantType.FACULTY: lambda: FacultyScraper(),
        }
        return scraper_factory[restaurant_type]()
    
    def get_parser(self) -> MenuParserInterface:
        if 'parser' not in self._instances:
            self._instances['parser'] = GPTClient(self._settings.gpt_api_key)
        return self._instances['parser']
    
    def get_api_client(self, is_dev: bool = False) -> APIClientInterface:
        key = f'api_client_{"dev" if is_dev else "prod"}'
        if key not in self._instances:
            base_url = self._settings.dev_api_base_url if is_dev else self._settings.api_base_url
            self._instances[key] = SpringAPIClient(base_url)
        return self._instances[key]
```

### 서비스 레이어에서 DI 사용
```python
# shared/services/scraping_service.py
class ScrapingService:
    def __init__(self, container: DependencyContainer):
        self._container = container
    
    async def scrape_and_process(self, date: str, restaurant_type: RestaurantType):
        # 런타임에 의존성 주입
        scraper = self._container.get_scraper(restaurant_type)
        parser = self._container.get_parser()
        api_client = self._container.get_api_client()
        
        # 비즈니스 로직 실행
        raw_menu = await scraper.scrape_menu(date)
        parsed_menu = await parser.parse_menu(raw_menu)
        
        # 프로덕션과 개발 환경 모두에 전송
        await api_client.post_menu(parsed_menu)
        await self._container.get_api_client(is_dev=True).post_menu(parsed_menu)
        
        return parsed_menu
```

## 4. 마이그레이션 단계별 계획

### Phase 1: 기반 구조 구축 (1-2일)
1. **새 디렉토리 구조 생성**
   ```bash
   mkdir -p functions/{config,shared/{models,serializers,repositories,services,utils},scraping/{views},scheduling/{views}}
   ```

2. **설정 및 DI 컨테이너 구현**
   - `config/settings.py` 생성 (기존 constant.py 이전)
   - `config/dependencies.py` 구현

3. **공통 모델 분리**
   - `shared/models/` 하위로 기존 models.py 분할
   - `shared/models/exceptions.py` 이전

### Phase 2: Repository 레이어 분리 (2-3일)
1. **인터페이스 정의**
   - `shared/repositories/interfaces.py` 작성

2. **스크래퍼 분리**
   ```python
   # 기존 get_dodam.py의 스크래핑 부분
   def get_dodam_from_soongguri(date) → DodamScraper.scrape_menu()
   def parse_raw_menu_text_from_html() → DodamScraper._parse_menu()
   ```

3. **클라이언트 분리**
   ```python
   # GPT 관련 로직
   extract_all_dishes_gpt() → GPTClient.parse_menu()
   
   # API 클라이언트
   post_dodam_lunch() → SpringAPIClient.post_menu()
   
   # Slack 클라이언트
   send_slack_message() → SlackClient.send_notification()
   ```

### Phase 3: Service 레이어 구현 (2일)
1. **ScrapingService 구현**
   ```python
   # 기존 fetch_and_refine_dodam() 로직을 서비스로 이전
   class ScrapingService:
       async def scrape_and_process(self, date, restaurant_type):
           # 기존 비즈니스 로직 통합
   ```

2. **NotificationService 구현**
   ```python
   # 스케줄링 Lambda의 알림 로직 분리
   class NotificationService:
       async def send_weekly_notifications(self, results):
   ```

### Phase 4: View 레이어 리팩토링 (1-2일)
1. **ScrapingView 구현**
   ```python
   # 기존 lambda_handler의 요청/응답 처리 부분만 남기고
   # 비즈니스 로직은 ScrapingService로 위임
   ```

2. **SchedulingView 구현**
   ```python
   # 기존 schedule_*.py의 Lambda 간 호출 로직 유지
   # 알림 로직은 NotificationService로 위임
   ```

### Phase 5: Lambda 핸들러 단순화 (1일)
```python
# 최종 Lambda 핸들러 형태
def lambda_handler(event, context):
    view = ScrapingView(RestaurantType.DODAM)
    return asyncio.run(view.handle(event, context))
```

## 5. 테스트 전략 개선

### 단위 테스트 (의존성 주입으로 목킹 용이)
```python
# 기존: 어려운 테스트
def test_fetch_and_refine_dodam():
    # 실제 웹 요청, GPT API 호출 필요

# 개선: 쉬운 테스트
def test_scraping_service():
    mock_scraper = Mock(spec=MenuScraperInterface)
    mock_parser = Mock(spec=MenuParserInterface)
    mock_api_client = Mock(spec=APIClientInterface)
    
    service = ScrapingService(mock_scraper, mock_parser, mock_api_client)
    result = await service.scrape_and_process("20241025", RestaurantType.DODAM)
```

### 통합 테스트 (실제 외부 의존성 사용)
```python
def test_end_to_end_scraping():
    container = DependencyContainer(Settings.from_env())
    service = ScrapingService(container)
    result = await service.scrape_and_process("20241025", RestaurantType.DODAM)
```

## 6. 예상 효과

### 유지보수성 개선
- **새 식당 추가**: 인터페이스 구현만으로 확장 가능
- **GPT 모델 변경**: GPTClient만 수정하면 됨
- **API 엔드포인트 변경**: SpringAPIClient만 수정하면 됨

### 테스트 용이성 개선
- **단위 테스트**: 각 컴포넌트 독립적 테스트 가능
- **목킹**: 인터페이스 기반으로 쉬운 목킹
- **통합 테스트**: 실제 의존성으로 전체 플로우 테스트

### 코드 가독성 개선
- **역할 분리**: 각 클래스가 단일 책임만 가짐
- **의존성 명시**: 생성자에서 필요한 의존성 명확히 표현
- **일관된 구조**: DRF 스타일로 통일된 구조

이 설계로 리팩토링하면 SOLID 원칙을 준수하면서도 Lambda의 특성을 살린 깔끔한 구조가 될 것입니다.