# 메뉴 파이프라인 운영 정책

베이스라인: `119c991db1b86d94cb4d9c1aea1478b8e7bfd61e` (2025-11-22, PR #26)
이후 219일간 변경 없이 운영됨.

---

## 1. 공통 정책

**타임존:** 베이스라인 cron은 UTC 기준이다. `ScheduleExpressionTimezone` 설정이 없다.
`date_utils.py`는 `pytz.timezone("Asia/Seoul")`로 KST를 계산한다. UTC+9 변환이 필요하다.
근거: `template.yml@119c991`, `date_utils.py:get_next_weekdays@119c991`

**dev/prod 발행 순서:** `send_to_api`는 dev를 먼저 발행하고, `is_dev=False`이면 prod를 추가 발행한다.
스케줄링 핸들러는 모두 `is_dev=False`로 호출한다.
근거: `scraping_service.py:send_to_api@119c991`, `scheduling/haksik.py@119c991`

**중복 제거 없음:** Spring POST 전 존재 여부를 확인하지 않는다. 같은 슬롯으로 여러 번 POST하면 모두 전달된다.
근거: `scraping_service.py:send_to_api@119c991`

**복수 코너 처리:** `get_successful_slots()`를 순회하며 슬롯마다 `post_menu`를 호출한다.
"중식1", "중식2", "중식3"은 각각 별도 POST가 발생한다. 모두 같은 time(LUNCH)으로 전송된다.
근거: `scraping_service.py:send_to_api@119c991`

**Spring POST 재시도:** `tenacity`로 3회 재시도, 2초 간격이다. 모두 실패하면 `MenuPostException`을 발생시킨다.
근거: `spring_api_client.py:@retry@119c991`

**Slack 알림:** 성공 시 날짜별로 `send_menu_notification`을 호출한다. 에러 시 `send_error_notification`을 호출한다.
에러 메시지 형식: `"식당명(날짜) Critical 에러 {예외 메시지}"`.
근거: `slack_client.py@119c991`, `scheduling_service.py@119c991`

---

## 2. 식당별 정책

### 학생식당 (HAKSIK, rcd=1)

| 항목 | 값 |
|------|-----|
| cron (UTC) | `cron(0 7 ? * SUN *)` = 일요일 16:00 KST |
| 대상 날짜 | 다음 주 월-금 5일 (`get_next_weekdays`) |
| `delayed_schedule=true` | 이번 주 월-금 (`get_current_weekdays`) |
| 소스 URL | `http://m.soongguri.com/m_req/m_menu.php?rcd=1&sdt={YYYYMMDD}` |

근거: `template.yml:HaksikSchedulingFunction@119c991`, `scheduling/haksik.py@119c991`, `settings.py:SOONGGURI_HAKSIK_RCD@119c991`

**슬롯-time 매핑:**

| 소스 슬롯 키 | Spring time | 가격 |
|-------------|-------------|------|
| "중식" 포함 | LUNCH | 5000 |
| "석식" 포함 | MORNING | 1000 (1000원 조식으로 처리) |

근거: `time_slot_strategy.py:HaksikTimeSlotStrategy@119c991`, `model.py:MenuPricing@119c991`

**휴무 처리:** HTML에 "오늘은 쉽니다." 또는 "휴무" 텍스트가 있으면 `HolidayException`을 발생시킨다.
`menu_texts`가 비어 있으면 `MenuFetchException`을 발생시킨다.
두 예외 모두 catch하여 Slack 에러 알림을 보내고 다음 날짜로 계속 진행한다.
근거: `haksik_scraper.py:_check_for_holidays@119c991`, `scheduling_service.py:process_weekly_schedule_general@119c991`

---

### 도담식당 (DODAM, rcd=2)

| 항목 | 값 |
|------|-----|
| cron (UTC) | `cron(0 7 ? * SUN *)` = 일요일 16:00 KST |
| 대상 날짜 | 다음 주 월-토 6일 (`WeekType.INCLUDE_SATURDAY`) |
| 소스 URL | `http://m.soongguri.com/m_req/m_menu.php?rcd=2&sdt={YYYYMMDD}` |

근거: `template.yml:DodamSchedulingFunction@119c991`, `scheduling/dodam.py@119c991`

**슬롯-time 매핑:**

| 소스 슬롯 키 | Spring time | 가격 |
|-------------|-------------|------|
| "중식" 포함 | LUNCH | 6000 |
| "석식" 포함 | DINNER | 6000 |
| "조식" 포함 | 무시 | - |

근거: `time_slot_strategy.py:DodamTimeSlotStrategy@119c991`

---

### 교직원식당 (FACULTY, rcd=7)

| 항목 | 값 |
|------|-----|
| cron (UTC) | `cron(0 7 ? * SUN *)` = 일요일 16:00 KST |
| 대상 날짜 | 다음 주 월-금 5일 |
| 소스 URL | `http://m.soongguri.com/m_req/m_menu.php?rcd=7&sdt={YYYYMMDD}` |

근거: `template.yml:FacultySchedulingFunction@119c991`, `scheduling/faculty.py@119c991`

**슬롯-time 매핑:** "중식" 포함 슬롯만 LUNCH(7000원)로 처리한다. 그 외는 무시한다.
근거: `time_slot_strategy.py:FacultyTimeSlotStrategy@119c991`

---

### 기숙사식당 (DORMITORY)

숭실대 생협 API를 사용하지 않는다. 별도 사이트를 사용한다.

| 항목 | 값 |
|------|-----|
| cron (UTC) | `cron(0 23 ? * SUN *)` = 월요일 08:00 KST |
| 대상 날짜 | 이번 주 월-일 7일 (`WeekType.FULL_WEEK`) |
| 소스 URL | `https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php` |

근거: `template.yml:DormitorySchedulingFunction@119c991`, `scheduling/dormitory.py@119c991`

**요청 파라미터:**
```
?viewform=B0001_foodboard_list&gyear={year}&gmonth={month}&gday={day}
```
`gday`는 요청 날짜(월요일)의 일(day)이다. 이 파라미터 하나로 해당 주 전체 메뉴를 가져온다.
근거: `dormitory_scraper.py:_fetch_menu_html@119c991`

**HTML 파싱:** `class="boxstyle02"` 테이블을 `make2d`로 2D 배열로 변환한다.
조식 컬럼은 스크래핑하지 않는다. 결과를 최대 7일치로 슬라이싱한다.
셀 텍스트에 "운영"이 포함되면 해당 슬롯을 제외한다.
근거: `dormitory_scraper.py:_extract_menu_texts,scrape_menu@119c991`

**슬롯-time 매핑:**

| 소스 슬롯 키 | Spring time | 가격 |
|-------------|-------------|------|
| "중식" | LUNCH | 5500 |
| "석식" | DINNER | 5500 |

근거: `time_slot_strategy.py:DormitoryTimeSlotStrategy@119c991`, `model.py:MenuPricing@119c991`

**Slack 알림:** `error_slots`가 없는 날짜만 `send_menu_notification`을 호출한다.
에러가 있는 날짜는 슬롯별로 `send_error_notification`을 호출한다.
근거: `scheduling_service.py:process_weekly_schedule_dormitory@119c991`

---

## 3. 현재 origin/main과의 차이

현재 main 최신 커밋: `a6b0de3` (PR #40)

| 항목 | 베이스라인 | 현재 main | 판정 |
|------|-----------|-----------|------|
| Lambda 구조 | 식당별 분리 핸들러 | 단일 `handler.py`, `OPERATION` env로 구분 | 의도된 개선 |
| 스케줄 트리거 | EventBridge -> Lambda 직접 | Step Functions State Machine 경유 | 의도된 개선 |
| 재시도 | Spring POST만 tenacity 3회 | State Machine으로 최대 9회, 2시간 간격 | 의도된 개선 |
| 중복 제거 | 없음 | `meal_exists` GET으로 확인 후 건너뜀 | 의도된 개선 |
| 복수 코너 POST | 슬롯마다 별도 POST | 첫 코너 발행 후 `meal_exists=true`로 나머지 건너뜀 | 회귀 (PR #39) |
| Slack 요약 알림 | 항상 전송 | PR #39에서 비활성화, PR #40에서 복원 | 회귀 후 수정 |
| 휴무 Slack 메시지 | 예외 메시지 원문 전송 | `"ℹ️ 휴무일"` 형식으로 정리 | 의도된 개선 |
| 타임존 설정 | cron UTC + Python pytz | `ScheduleExpressionTimezone: Asia/Seoul` | 의도된 개선 |
| 기숙사 스케줄 | 월요일 08:00 KST 1회 | 매일 08:00, 09:00, 10:00 KST 3회 | 의도된 개선 |

**복수 코너 회귀 상세 (PR #39):**
현재 main의 `_run_schedule`은 발행 전에 `meal_exists`로 Spring API에 GET 요청을 보낸다.
"중식1" 발행 성공 후 "중식2"를 처리할 때 `meal_exists(LUNCH)`가 true를 반환한다.
따라서 "중식2", "중식3"은 발행되지 않는다. 베이스라인은 모두 발행했다.
근거: `handler.py:publish_if_missing,_run_schedule@origin/main`

**Slack 요약 알림 회귀 상세 (PR #39, PR #40):**
PR #39 이후 스케줄 Input에 `"notify_summary":false`가 설정되어 Slack 알림이 전송되지 않았다.
PR #40에서 `"notify_summary":true`로 복원되었다. 현재 main은 정상이다.
근거: `template.yml:WeeklySeoulSchedule Input@origin/main`
