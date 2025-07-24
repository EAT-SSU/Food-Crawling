import pytest

from functions.common.utils import get_current_weekdays
from functions.scrapping.get_dodam import fetch_and_refine_dodam, get_dodam_from_soongguri


@pytest.mark.unit
def test_fetch_and_refine_dodam():
    menu: dict = fetch_and_refine_dodam("20240325")

    # 2024년 3월 25일의 도담식당 메뉴가 다음과 같은지 확인합니다.

    # {'석식1': ['제육볶음', '오징어청경채무침'], '중식1': ['뼈없는닭갈비', '크레잇고기왕교자만두찜'], '중식4': ['샐러드비빔밥', '계란후라이']}
    assert "뼈없는닭갈비" in menu["중식1"] and \
           "샐러드비빔밥" in menu["중식4"] and \
           "제육볶음" in menu["석식1"]


@pytest.mark.unit
def test_get_dodam_from_soongguri():
    response = get_dodam_from_soongguri("20240325")
    assert response.status_code == 200


@pytest.mark.unit
def test_post_dodam_lunch_dev():
    weekdays = get_current_weekdays()
    menus = []
    for date in weekdays:
        try:
            menus.append(fetch_and_refine_dodam(date))
        except:
            pass
