# Food Scrapper Serverless

AWS Lambda를 이용하여 학교 식당 메뉴를 스크랩하고 Slack으로 알림을 보내주는 서버리스 애플리케이션입니다. AWS SAM으로 인프라를 관리합니다.

## 기능

- 학교 식당 웹사이트에서 주간 메뉴 정보 스크랩
- GPT(`gpt-5.6-luna`)로 메인메뉴 추출 및 영문 번역
- Spring 서버에 메뉴 데이터 게시
- Slack 채널에 처리 결과 알림

## 기술 스택

- AWS Lambda: 메뉴 스크랩 및 가공 로직 실행
- AWS IAM: 인증된 사용자와 역할에 Lambda 수동 호출 권한 부여
- AWS EventBridge: 스케줄링된 스크랩 작업 관리
- AWS Step Functions: 기숙사식당 재시도 워크플로우
- AWS SAM: 인프라 관리 및 배포 자동화

## 런타임 아키텍처

모든 Lambda 함수는 단일 핸들러 `functions.handler.lambda_handler`를 공유하며, 각 함수 리소스에 설정된 `OPERATION` 환경 변수로 동작을 구분합니다.

### 다섯 개 런타임 모듈

| 모듈 | 역할 |
|------|------|
| `functions/handler.py` | 이벤트 파싱, 오퍼레이션 디스패치, 관찰 이벤트 발행 |
| `functions/scraper.py` | 식당별 웹 스크래핑, `MealRecord` 반환 |
| `functions/menu_ai.py` | GPT 호출, 메인메뉴 추출 및 검증 |
| `functions/clients.py` | Spring POST, Slack 알림 |
| `functions/config.py` | 오퍼레이션별 환경 변수 로드 |

### GPT 모델 및 메뉴 추출 정책

- **모델**: `gpt-5.6-luna` (고정)
- **도구 호출**: `extract_main_menus` 단일 호출, strict 모드, 인덱스 기반 출력
- **HAKSIK / DODAM / FACULTY**: 사이트 HTML에 포함된 영문 텍스트를 그대로 복사(`nameEn`은 소스 원문 verbatim)
- **DORMITORY**: GPT가 영문 번역 생성, 정확히 `min(3, 메뉴 수)` 개 후보 반환

### mainMenus 및 unmatchedMainMenus 처리

- Spring POST 요청에 `mainMenus` 필드는 GPT 결과가 있을 때만 포함됩니다(선택적).
- Spring 응답에 `unmatchedMainMenus`가 포함되면 accepted 경고로 처리하고 Slack 요약에 기록합니다. Spring 쓰기는 성공으로 간주합니다.

### 식당별 슬롯 정책

| 식당 | 슬롯 | Spring time | 가격 |
|------|------|-------------|------|
| DODAM | 중식 | LUNCH | 6000 |
| DODAM | 석식 | DINNER | 6000 |
| HAKSIK | 중식 | LUNCH | 5000 |
| HAKSIK | 석식 | MORNING | 1000 |
| FACULTY | 중식 | LUNCH | 7000 |
| DORMITORY | 중식 | LUNCH | 5500 |
| DORMITORY | 석식 | DINNER | 5500 |

## 인프라 (9개 Lambda 리소스)

모든 함수는 `functions.handler.lambda_handler`를 사용하며 공개 API 엔드포인트나 Function URL이 없습니다.

| SAM 논리 ID | OPERATION | 설명 |
|-------------|-----------|------|
| `DodamScrapingFunction` | `scrape_dodam` | 도담식당 단일 날짜 스크랩 (직접 호출용) |
| `HaksikScrapingFunction` | `scrape_haksik` | 학생식당 단일 날짜 스크랩 (직접 호출용) |
| `FacultyScrapingFunction` | `scrape_faculty` | 교직원식당 단일 날짜 스크랩 (직접 호출용) |
| `DormitoryScrapingFunction` | `scrape_dormitory` | 기숙사식당 주간 스크랩 (직접 호출용) |
| `DodamSchedulingFunction` | `schedule_dodam` | 도담식당 주간 스케줄 |
| `HaksikSchedulingFunction` | `schedule_haksik` | 학생식당 주간 스케줄 |
| `FacultySchedulingFunction` | `schedule_faculty` | 교직원식당 주간 스케줄 |
| `DormitorySchedulingFunction` | `schedule_dormitory` | 기숙사식당 주간 스케줄 (Step Functions 호출) |
| `NotifyFailureFunction` | `notify_final_failure` | 기숙사 최종 실패 Slack 알림 |

각 함수에 대응하는 CloudWatch 로그 그룹(`*LogGroup`)이 9개 추가로 존재하며, 로그는 30일간 보존됩니다.

### 자동 스케줄

- **도담/학생/교직원식당 스케줄링**: 매주 일요일 오후 4시 KST (UTC 07:00) 자동 실행
- **기숙사식당 Step Functions**: 매주 일요일 23:00 UTC (월요일 08:00 KST) 자동 실행, 내부에서 `DormitorySchedulingFunction`과 `NotifyFailureFunction` 호출

### 직접 호출 vs 스케줄 실행

- **직접 호출(scrape_*)**: `is_dev=True` — dev Spring 클라이언트만 호출, dev 실패가 critical
- **스케줄 실행(schedule_*)**: dev와 prod 모두 호출, prod 실패만 critical

### 기숙사 Step Functions 재시도

- **도메인 재시도** (`RetryableEmptyMenuError`, `RetryableApiSendError`): 최대 5회, 7200초 간격, 백오프 1.0
- **Lambda 일시 오류 재시도** (`Lambda.ServiceException` 등): 최대 3회, 2초 간격, 백오프 2.0
- 모든 재시도 소진 후 `NotifyFailureFunction`으로 최종 실패 알림

### 최종 실패 알림

`notify_final_failure`의 Slack 호출이 실패하면 예외가 그대로 전파됩니다. 보호할 Spring 쓰기가 없으므로 격리하지 않습니다.

## 환경 설정

### 필요 조건

- Python 3.11
- AWS SAM CLI
- AWS 계정 및 CLI 구성

### AWS SAM 설정

1. AWS SAM CLI 설치:

**macOS (Homebrew):**
```bash
brew install aws-sam-cli
```

**Linux/Windows:** [AWS SAM CLI 설치 가이드](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html) 참조

2. AWS CLI 설정:
```bash
aws configure
```

## 배포 방법

### 1. 환경 설정 파일 준비

`env.json` 파일 생성 (루트 디렉토리):
```json
{
  "Parameters": {
    "GPTApiKey": "your-openai-api-key",
    "SlackWebhookUrl": "your-slack-webhook-url",
    "ApiBaseUrl": "your-production-api-url",
    "DevApiBaseUrl": "your-development-api-url"
  }
}
```

### 2. 배포 설정 파일

`samconfig.toml` 파일 생성 (루트 디렉토리):
```toml
version = 0.1
[default]
[default.deploy]
[default.deploy.parameters]
stack_name = "food-scrapper-default"
region = "ap-northeast-2"
confirm_changeset = true
capabilities = "CAPABILITY_IAM"
parameter_overrides = [
    "GPTApiKey=your-gpt-api-key",
    "SlackWebhookUrl=your-slack-webhook-url",
    "ApiBaseUrl=your-api-base-url",
    "DevApiBaseUrl=your-dev-api-base-url"
]
```

> ⚠️ **보안 주의사항**: `samconfig.toml`에는 민감한 정보가 포함되므로 `.gitignore`에 추가하세요.

### 3. 빌드 및 배포

#### 기존 Lambda 로그 그룹 사전 확인

이 템플릿은 9개 Lambda 함수의 `/aws/lambda/...` 로그 그룹을 CloudFormation 리소스로 관리하고 로그를 30일간 보존합니다. 기존 배포에서 같은 이름의 로그 그룹이 이미 자동 생성되었다면, **배포 전에 CloudFormation IMPORT change set**으로 9개 로그 그룹을 현재 스택 소유로 가져와야 합니다.

기존 로그 그룹의 import가 완료되지 않았거나 import를 수행할 IAM 권한이 없다면, 같은 이름의 리소스를 생성하려 하지 말고 **배포를 중단**해야 합니다. 기존 로그 그룹을 삭제해서 충돌을 해결하지 마세요.

```bash
# 애플리케이션 빌드
sam build

# 템플릿 검증
sam validate

# 초회 배포 (가이드 모드)
sam deploy --guided

# 이후 배포
sam deploy
```

### 4. 로컬 개발 및 테스트

```bash
# 특정 함수 로컬 실행
sam local invoke HaksikSchedulingFunction --event event.json --env-vars env.json

# 로그 확인
sam logs --stack-name food-scrapper-default --tail
```

### 5. 배포된 함수 수동 실행

공개 HTTP 엔드포인트는 생성하지 않습니다. 수동 작업은 `lambda:InvokeFunction` 권한이 있는 IAM 자격 증명으로 AWS CLI의 `aws lambda invoke`를 사용합니다.

```bash
# 스택에서 실제 함수 이름을 확인한 뒤 IAM 인증으로 호출
aws lambda invoke \
  --function-name <stack-function-name> \
  --cli-binary-format raw-in-base64-out \
  --payload file://event.json \
  response.json
```

호출 대상은 배포된 `DodamScrapingFunction`, `HaksikScrapingFunction`, `FacultyScrapingFunction`, `DormitoryScrapingFunction`, `DodamSchedulingFunction`, `HaksikSchedulingFunction`, `FacultySchedulingFunction`, `DormitorySchedulingFunction`, `NotifyFailureFunction`의 실제 함수 이름 중에서 선택합니다. IAM 자격 증명은 `aws configure` 또는 승인된 프로파일로 설정하고 공개 URL이나 익명 호출을 사용하지 않습니다.

## 로컬 검증

```bash
# 전체 오프라인 테스트 (CI와 동일한 명령)
uv run pytest -q

# 컴파일 검사
uv run python -m compileall -q functions tests

# SAM 템플릿 검증
sam validate --lint

# SAM 빌드
sam build --no-cached
```
