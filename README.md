# Food Scrapper Serverless

Food Scrapper Serverless는 AWS Lambda를 이용하여 학교 식당 메뉴를 스크랩하고, Slack으로 알림을 보내주는 서버리스 애플리케이션입니다. 이 프로젝트는 Serverless Framework를 사용하여 AWS 서비스에 배포됩니다.

## 기능

- 학교 식당 웹사이트에서 일일 메뉴 정보 스크랩
- 스크랩된 메뉴 정보를 가공하여 Slack 채널에 메시지로 전송

## 기술 스택

- AWS Lambda: 메뉴 스크랩 및 가공 로직 실행
- AWS API Gateway: HTTP 요청에 대한 엔드포인트 제공
- AWS Step Functions: 스크랩과 알림 전송 프로세스 관리
- Serverless Framework: 인프라 관리 및 배포 자동화

## 환경 설정

### 필요 조건

- Node.js (버전 12 이상)
- Serverless Framework
- AWS 계정 및 CLI 구성

### Serverless Framework 세팅

1. Serverless Framework 설치:

```bash
npm install -g serverless
```

2. secrets.yml 파일 생성 (노션 참조)
3. serverless 의존성 폴더 생성
```bash
mkdir -p python-requirements-layer/python/lib/python3.9/site-packages
pip install -r requirements.txt -t python-requirements-layer/python/lib/python3.9/site-packages
```
4. serverless plugin 설치
```bash
serverless plugin install -n serverless-step-functions
```
5. serverless credential 등록 (노션 참조)


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

