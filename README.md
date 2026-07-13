# Food Scrapper Serverless

Food Scrapper Serverless는 AWS Lambda를 이용하여 학교 식당 메뉴를 스크랩하고, Slack으로 알림을 보내주는 서버리스 애플리케이션입니다. 이 프로젝트는 Serverless Framework를 사용하여 AWS 서비스에 배포됩니다.

## 기능

- 학교 식당 웹사이트에서 일일 메뉴 정보 스크랩
- 스크랩된 메뉴 정보를 가공하여 Slack 채널에 메시지로 전송

## 기술 스택

- AWS Lambda: 메뉴 스크랩 및 가공 로직 실행
- AWS IAM: 인증된 사용자와 역할에 Lambda 수동 호출 권한 부여
- AWS EventBridge: 스케줄링된 스크랩 작업 관리
- AWS SAM: 인프라 관리 및 배포 자동화

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

3. Python 의존성 레이어 생성:
```bash
mkdir -p python-requirements-layer/python/lib/python3.11/site-packages
pip install -r requirements.txt -t python-requirements-layer/python/lib/python3.11/site-packages
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

### 자동 스케줄

- **도담/학생/교직원식당**: 매주 일요일 오후 4시 (KST) 자동 실행
- **기숙사식당**: 매주 월요일 오전 8시 (KST) 자동 실행


## Structure

```mermaid
sequenceDiagram
    participant schedule_dodam
    participant get_dodam
    participant WebScraping
    participant OpenAI
    participant SpringServer
    participant SNS
    participant Slack

    loop 매일
        schedule_dodam ->>+ get_dodam: 날짜 전달
        get_dodam ->>+ WebScraping: 숭실대 웹사이트 스크래핑
        WebScraping -->>- get_dodam: 스크래핑 데이터 반환
        get_dodam ->>+ OpenAI: 메인메뉴 고르기 요청
        OpenAI -->>- get_dodam: 메인메뉴 데이터 반환
        get_dodam ->>+ SpringServer: 메인메뉴 POST 요청
        SpringServer -->>- get_dodam: 요청 처리 완료
        get_dodam -->>- SNS: 메시지 발행
    end

    SNS -->> Slack: 메시지 전달
    Slack ->> schedule_dodam: 처리 완료 응답
```
