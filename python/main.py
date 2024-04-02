import sentry_sdk
from fastapi import FastAPI
from fastapi import HTTPException
import os
import sys

from Object import Dormitory
from practice import practice_dodam
from practice import practice_student_restarant
from practice import HolidayError
from practice import NetworkError



sys.path.append("/app/python/")


sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    traces_sample_rate=1.0,
)


app = FastAPI()


@app.get("/foods/dodam",
         description="도담식당의 하루 치 메뉴를 받아오는 api입니다. date format->yyyymmdd. ex)20230502")
def get_dodam(date: str):

    try:
        menu_dict = practice_dodam(date=date)
        return menu_dict
    except HolidayError as h_e:
        raise HTTPException(status_code=400, detail=h_e.args[0])
    except NetworkError as n_e:
        raise HTTPException(status_code=400, detail=n_e.args[0])


@app.get("/foods/school_cafeteria",
         description="학생식당의 하루 치 메뉴를 받아오는 api입니다, date format->yyyymmdd. ex)20230502")
def get_school_cafeteria(date: str):

    try:
        menu_dict = practice_student_restarant(date=date)
        return menu_dict
    except HolidayError as h_e:
        raise HTTPException(status_code=400, detail=h_e.args[0])
    except NetworkError as n_e:
        raise HTTPException(status_code=400, detail=n_e.args[0])



@app.get("/foods/dormitory",
         description="기숙사 식당의 일주일 치 메뉴를 받아오는 api입니다, date format->yyyymmdd. ex)20230502")
def get_school_cafeteria(date: str):
    today = Dormitory(date)
    return today.get_menu()

@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0

