# CLAUDE.md

이 저장소는 숭실대 식당 메뉴를 크롤링해서 EAT-SSU Spring API(prod, dev)에 올리는 AWS SAM Lambda 프로젝트다.
아래 규칙은 실제 장애에서 나온 것이다. 작업 전에 반드시 읽고, 어기지 않는다.

## 1. 데이터 모델 (가장 많이 틀린 부분)

- **Spring의 한 시간대(`time`)에는 식단이 여러 건 들어간다.** 한 시간대에 식단이 하나라고 가정하지 않는다.
  - 학생식당(HAKSIK): 중식1, 중식2, 중식3이 모두 `LUNCH`에 들어간다. 석식1은 `MORNING`에 들어간다.
  - 도담(DODAM): 중식1, 중식4가 모두 `LUNCH`에 들어간다.
  - 기숙사, 교직원식당은 현재 시간대당 코너가 하나다. 이것도 바뀔 수 있다.
- 중복 확인과 완성도 판정은 **코너 단위**로 한다. "시간대에 1건 이상 있음"을 "완료"로 판정하지 않는다.
  - 2026-10-04 장애: 시간대 단위 중복 확인 때문에 학생식당 중식2, 중식3과 도담 중식4가 한 주 내내 업로드되지 않았다.
- 시간대 매핑은 `functions/config.py`의 `slots`만 따른다. 이름으로 추측하지 않는다. (학생식당 석식은 `MORNING`이다.)

## 2. Spring API

- `POST /meals/with-price`는 같은 시간대에 메뉴 이름 목록(정렬 후)이 정확히 같은 식단이 있으면 기존 `mealId`를 돌려준다. 이름이 조금이라도 다르면 새 식단이 생긴다(LLM 출력 차이).
- 조회: `GET {base}/meals?date=YYYYMMDD&restaurant=CODE&time=TIME&language=KO`. 인증이 필요 없다. `result`는 식단 목록이다.
- POST 전에는 반드시 GET으로 확인한다. GET이 실패하면 POST하지 않는다.
- prod는 `https://eat-ssu.tech`, dev는 `https://dev.eat-ssu.tech`다. 한 스택이 두 곳 모두에 POST한다.

## 3. 원본 사이트의 특이 동작

- **기숙사 사이트는 `gday`에 일요일을 넣으면 다음 주 페이지를 준다.** 항상 그 주의 월요일로 요청한다(`scraper.py`).
- 숭실 생협(`m.soongguri.com`) 휴무 표기는 문장형이다. 예: "한글날 로 휴무 입니다.", "개교기념일 행사 로 웰빙 코너 운영하지 않습니다." 이런 문장을 메뉴로 올리지 않는다.
- 기숙사는 주간 식단을 늦게 올릴 수 있다(연휴 직후 등). 한 번 비어 있다고 그 날짜를 포기하지 않는다.

## 4. 동작을 바꿀 때 지킬 것

- **요청받지 않은 동작을 끄거나 바꾸지 않는다.** 2026-10 PR #39에서 성공 Slack 알림을 임의로 꺼서, 사용자가 업로드 결과를 받지 못했다.
- Slack 성공 요약은 새로 POST한 날짜에만 보낸다. 실패 경고(기숙사 10:00, 일요일 재시도 소진)는 유지한다.
- 스케줄 cron은 KST(`ScheduleExpressionTimezone: Asia/Seoul`) 기준이다. UTC로 읽지 않는다.
  - 기숙사: 매일 08:00, 09:00, 10:00, 이번 주 대상
  - 다른 식당: 일요일 16:00 다음 주 대상(Step Functions 재시도), 월요일부터 목요일까지 16:05 이번 주 남은 날짜 대상
- 재시도가 자정을 넘으면 `delayed_schedule`로 같은 주를 계속 본다. 재시도 여부는 `trigger == step_functions`로 판단한다.

## 5. 테스트

- 새 로직에는 **한 시간대에 코너가 여러 개인 경우**를 반드시 테스트한다(전부 신규, 일부 존재, 전부 존재).
- 테스트 fixture가 실제 원본과 다를 수 있다. 원본 구조를 바꾸는 로직은 실제 사이트로도 한 번 확인한다(쓰기 없이 `fetch_meals`만 호출).
- `uv run pytest -q`, `sam validate --lint`가 통과해야 한다.

## 6. 배포

- dev 전용 스택은 없다. `food-scrapper` 스택 배포는 곧 prod 반영이다. 배포 전에 사용자 승인을 받는다.
- **캐시 없이 빌드한다.** `rm -rf .aws-sam` 후 빌드한다. `--cached` 빌드가 오래된 `functions/config/` 패키지를 포함해서 Lambda가 import 오류로 멈춘 적이 있다.
- `ReservedConcurrentExecutions`를 넣지 않는다. 계정 동시 실행 한도가 10이라 배포가 실패한다.
- CloudFormation은 같은 논리 ID의 리소스 타입 변경을 거부한다. 타입을 바꾸면 논리 ID도 바꾼다.
- GitHub에는 자동 배포가 없다. 머지와 배포는 별개다.

## 7. 배포 후 검증 (건수만 보지 않는다)

- **원본 코너 목록과 Spring GET 결과를 날짜별, 코너별로 1:1 대조한다.** "1건 이상 있음"은 검증이 아니다.
  - 원본: `fetch_meals(CODE, YYYYMMDD)`의 `source_slot`과 대표 메뉴
  - Spring: 같은 날짜와 시간대의 `result` 건수와 첫 메뉴 이름
- prod와 dev를 모두 확인한다. 슬롯마다 중복이 없는지도 확인한다.
- 날짜와 요일은 `date` 명령으로 확인한다. 추측하지 않는다.

## 8. 운영 작업

- prod에 쓰는 수동 실행이나 직접 POST는 사용자 승인 후에만 한다. 먼저 dry-run으로 올릴 내용을 보여 준다.
- 수동 POST 전에도 GET으로 같은 대표 메뉴가 없는지 확인한다.
- AWS 접근: `AWS_PROFILE=eatssu`, 리전 `ap-northeast-2`.
