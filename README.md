# Food Scrapper Serverless

숭실대 식당 메뉴를 크롤링해서 EAT-SSU Spring API(prod, dev)에 올리는 AWS SAM Lambda 프로젝트입니다.
작업 전에 `CLAUDE.md`의 운영 규칙을 먼저 읽습니다.

## 동작 흐름

스케줄 실행 한 번은 다음 순서로 진행합니다.

1. 원본 사이트에서 대상 날짜의 코너를 읽습니다(`scraper.py`).
2. 환경(dev, prod)과 시간대마다 Spring 기존 식단을 GET으로 조회합니다.
3. `fill` 모드에서는 기존 식단을 코너에 매칭하고, 매칭되지 않은 코너만 GPT로 해석합니다(`menu_ai.py`).
4. 시간대 전체 코너 배열을 한 번에 PUT합니다(`clients.py`).
5. 변경이 있는 날짜에만 Slack 요약을 보냅니다.

재시도는 별도 워크플로가 아니라 반복되는 cron 실행입니다. 매번 GET 후 시간대 전체를 PUT하므로 다시 실행해도 중복이 생기지 않습니다.

## 런타임 모듈 (`src/functions/`)

| 모듈 | 역할 |
|------|------|
| `handler.py` | 이벤트 검증, 날짜 계산(KST), 코너 매칭, 발행, Slack 알림 |
| `scraper.py` | 숭실 생협과 기숙사 사이트 파싱, 기숙사 릴레이, 차단 페이지 감지 |
| `menu_ai.py` | GPT(`gpt-5.6-luna`) 호출, 메뉴 이름과 대표 메뉴 검증 |
| `clients.py` | Spring GET/PUT, Slack 전송과 메시지 형식 |
| `config.py` | 식당별 시간대 매핑과 가격, 환경 변수 |

### 식당별 시간대 정책

| 식당 | 원본 코너 | Spring time | 가격 |
|------|-----------|-------------|------|
| DODAM | 중식1, 중식4 | LUNCH | 6000 |
| DODAM | 석식1 | DINNER | 6000 |
| HAKSIK | 중식1, 중식2, 중식3 | LUNCH | 5000 |
| HAKSIK | 석식1 | MORNING | 1000 |
| FACULTY | 중식1 | LUNCH | 7000 |
| DORMITORY | 중식 | LUNCH | 5500 |
| DORMITORY | 석식 | DINNER | 5500 |

한 시간대에 코너가 여러 개 들어갈 수 있으므로, 발행 여부는 코너 단위로 판정합니다.

## 이벤트

Lambda는 `MenuFunction` 하나이며 이벤트로 동작을 정합니다.

```json
{
  "restaurant": "DORMITORY|HAKSIK|DODAM|FACULTY",
  "dates": "current_week|next_week|remaining_week",
  "date": "YYYYMMDD",
  "mode": "fill|force",
  "final": false,
  "dry_run": false,
  "environments": ["dev", "prod"]
}
```

- `dates`와 `date` 중 하나를 넘깁니다. 오늘(KST) 이전 날짜는 항상 제외합니다.
- `mode` 기본값은 `fill`입니다. `force`는 모든 코너를 다시 해석합니다(수동 복구용).
- `environments` 기본값은 `["dev"]`입니다. 스케줄은 `["dev","prod"]`를 넘깁니다.
- `final: true`이면 아직 prod에 없는 코너를 Slack으로 경고합니다.
- `dry_run: true`이면 PUT과 Slack 없이 올릴 내용을 응답 본문 `planned`에 돌려줍니다.

### Slack 알림

- 성공 요약: PUT으로 식단을 생성하거나 삭제한 날짜
- 리뷰 경고: 리뷰 때문에 Spring이 유지한 식단(`keptWithReviews`)
- 마감 경고: `final: true` 실행에서 발행되지 않은 코너(날짜, 시간대, 코너, 환경)

원본을 읽지 못한 경우(기숙사 미게시, 차단 페이지, HTTP 오류)에는 PUT하지 않습니다. 이때는 코너 수를 알 수 없으므로 prod에 해당 날짜와 시간대 식단이 1건 이상 있으면 발행된 것으로 봅니다.

## 스케줄 (KST, `ScheduleExpressionTimezone: Asia/Seoul`)

| 식당 | 시각 | 대상 | final |
|------|------|------|-------|
| 기숙사 | 매일 08:00, 09:00 | 이번 주 | false |
| 기숙사 | 매일 10:00 | 이번 주 | true |
| 학생식당, 도담, 교직원식당 | 일요일 16:00 | 다음 주 | false |
| 학생식당, 도담, 교직원식당 | 일요일 20:00 | 다음 주 | true |
| 학생식당, 도담, 교직원식당 | 월-목 16:05 | 이번 주 남은 날짜 | true |

## 기숙사 릴레이

기숙사 사이트는 2026-10-28부터 데이터센터 IP에 호스팅 점검 페이지(HTTP 200, 제목 `솔루션의 강국`)를 반환합니다. 이 페이지는 `SOURCE_BLOCKED`로 분류합니다.
`DormitoryRelayUrl` 파라미터를 설정하면 Lambda는 `{relay}?gyear=..&gmonth=..&gday=..`로 요청하고 `X-Relay-Token` 헤더에 `DormitoryRelayToken`을 넣습니다. 릴레이는 기숙사 페이지 바이트(EUC-KR)를 그대로 돌려줘야 합니다.

## 인프라 (`template.yml`)

- `MenuFunction`: Lambda 하나, `CodeUri: src/`(런타임 코드만 포함)
- `PythonRequirementsLayer`: `ContentUri: layer/`(`layer/requirements.txt`만 포함)
- `MenuFunctionLogGroup`: 로그 30일 보존
- 파라미터: `GPTApiKey`, `SlackWebhookUrl`, `ApiBaseUrl`, `DevApiBaseUrl`, `DormitoryRelayUrl`, `DormitoryRelayToken`

SAM은 `.samignore`를 따르지 않으므로 `env.json`, `.env`, `tests/` 등이 패키지에 들어가지 않도록 코드 디렉터리를 분리했습니다.

## 로컬 검증

```bash
uv run pytest -q
sam validate --lint
make build   # layer/requirements.txt 생성, rm -rf .aws-sam, sam build --no-cached
find .aws-sam/build/MenuFunction -maxdepth 1   # functions만 있어야 합니다
```

## 배포

`food-scrapper` 스택 배포는 곧 prod 반영입니다. 사용자 승인 후에만 실행합니다.

```bash
# 비밀 값은 macOS 키체인(account eatssu)에 저장합니다.
security add-generic-password -U -a eatssu -s food-scrapper-gpt-api-key -w
security add-generic-password -U -a eatssu -s food-scrapper-slack-webhook -w
security add-generic-password -U -a eatssu -s food-scrapper-dorm-relay-token -w

# 일반 값은 환경 변수로 넘깁니다. 없는 값은 이전 스택 값을 유지합니다.
API_BASE_URL=https://eat-ssu.tech DEV_API_BASE_URL=https://dev.eat-ssu.tech \
DORMITORY_RELAY_URL=https://relay.example/dorm make deploy
```

`deploy.sh`는 `env.json`과 `.env`를 읽지 않고, 비밀 값을 출력하지 않습니다.

## 수동 실행

```bash
aws lambda invoke --function-name <MenuFunction 실제 이름> \
  --cli-binary-format raw-in-base64-out \
  --payload '{"restaurant":"HAKSIK","date":"20261102","dry_run":true,"environments":["dev","prod"]}' \
  response.json
```

prod에 쓰는 수동 실행은 dry-run 결과를 확인하고 승인받은 뒤에만 합니다.
