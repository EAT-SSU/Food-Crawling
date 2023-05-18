from typing import Optional
from fastapi import FastAPI,status
from typing import *
from Object import Dodam_or_School_Cafeteria ,Dodam
from Object import Dormitory
import os
# from fastapi.responses import JSONResponse
# from pydantic import BaseModel
import sys
sys.path.append("/app/python/")

import sentry_sdk


sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production,
    traces_sample_rate=1.0,
)


app = FastAPI()

'''
    ?    rcd=2  &   sdt=20230206
    rcd=1 -> 학생식당
    rcd=2 -> 숭실도담식당

    sdt   -> 날짜

'''


@app.get("/foods/dodam",
        description="도담식당의 하루 치 메뉴를 받아오는 api입니다. date format->yyyymmdd. ex)20230502")
def get_dodam(date:str):
    # date = datetime.strptime(date,'%y%m%d')
    todaymenu=Dodam_or_School_Cafeteria(2,date)   
    return todaymenu.get_menu()

@app.get("/foods/school_cafeteria",
        description="학생식당의 하루 치 메뉴를 받아오는 api입니다, date format->yyyymmdd. ex)20230502")
def get_school_cafeteria(date:str):
    todaymenu=Dodam_or_School_Cafeteria(1,date)   
    a=todaymenu.get_menu()
    return todaymenu.menu

@app.get("/foods/dormitory",
        description="기숙사 식당의 일주일 치 메뉴를 받아오는 api입니다, date format->yyyymmdd. ex)20230502")
def get_school_cafeteria(date:str):
    todaymenu=Dormitory(date)   
    todaymenu.refine_table()
    todaymenu.get_table()
    return todaymenu.dict

@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0

@app.get("/test")
def get_dodam(date: str):
    today=Dodam(date=date)
    today.get_menu()

    return today.menu





    
        