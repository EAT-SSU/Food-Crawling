import pytest

from functions.scrapping.get_haksik import fetch_and_refine_haksik, get_haksik_from_soongguri, post_haksik_lunch


@pytest.mark.unit
def test_fetch_and_refine_haksik():
    menu: dict = fetch_and_refine_haksik("20240325")

    # 2024년 3월 25일의 학식 메뉴가 다음과 같은지 확인합니다.

    # {'석식1': ['얼큰콩나물국 & 닭살데리야끼볶음', '새송이버섯볶음', '아삭이고추된장무침', '도시락김', '맛김치', '찰흑미밥'], '중식1': ['꼬치어묵우동', '칠리탕수육', '단무지'], '중식2': ['고추장불고기덮밥&계란후라이', '칠리탕수육'], '중식3': ['함박스테이크&파인애플볶음밥', '만다린샐러드']}
    assert "꼬치어묵우동" in menu["중식1"] and \
           '고추장불고기덮밥&계란후라이' in menu["중식2"] and \
           "함박스테이크&파인애플볶음밥" in menu["중식3"] and \
           '얼큰콩나물국 & 닭살데리야끼볶음' in menu["석식1"]  # '["석식1"]'이 아니라 'menu["석식1"]'로 수정

@pytest.mark.unit
def test_get_haksik_from_soongguri():
    response = get_haksik_from_soongguri("20240325")
    assert response.status_code == 200

@pytest.mark.unit
def test_post_haksik_lunch():
    response = post_haksik_lunch("20240325", ["꼬치어묵우동", "칠리탕수육"])

    assert response.status_code == 200
