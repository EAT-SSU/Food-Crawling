import sentry_sdk
from fastapi import FastAPI

from Object import School_Cafeteria
from Object import Dormitory
from Object import Dodam

import os
import sys

sys.path.append("/app/python/")


sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production,
    traces_sample_rate=1.0,
)


app = FastAPI()


@app.get("/foods/dodam",
         description="도담식당의 하루 치 메뉴를 받아오는 api입니다. date format->yyyymmdd. ex)20230502")
def get_dodam(date: str):
    today = Dodam(date=date)
    today.get_menu()

    return today.menu


@app.get("/foods/school_cafeteria",
         description="학생식당의 하루 치 메뉴를 받아오는 api입니다, date format->yyyymmdd. ex)20230502")
def get_school_cafeteria(date: str):
    today = School_Cafeteria(date=date)
    today.get_menu()

    return today.menu


@app.get("/foods/dormitory",
         description="기숙사 식당의 일주일 치 메뉴를 받아오는 api입니다, date format->yyyymmdd. ex)20230502")
def get_school_cafeteria(date: str):
    todaymenu = Dormitory(date)
    todaymenu.refine_table()
    todaymenu.get_table()
    return todaymenu.dict


@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0





    
        