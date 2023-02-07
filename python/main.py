import urllib.request
from bs4 import BeautifulSoup
import re
from typing import Optional
from fastapi import FastAPI

app = FastAPI()

'''
    ?    rcd=2  &   sdt=20230206
    rcd=1 -> 학생식당
    rcd=2 -> 숭실도담식당

    sdt   -> 날짜

'''
@app.get("/foods/{day}/{restaurantType}",description="도담식당과 학생식당의 메뉴를 받아오는 api입니다. restaurantType={1:학생식당,2:숭실도담식당} day={yyyymmdd} 현재 도담식당만 가능합니다.")
def getTodayMenu(restaurantType:int, day:Optional[int]):
    webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={restaurantType}&sdt={day}')
    soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')
    if (restaurantType==1): #학생식당
        pass
        #일단 학생식당 부분은 pass

    if (restaurantType==2): #도담식당
        result=soup.find_all(text=re.compile("#.*"))
        for index,item in enumerate(result):
            result[index]=item.strip().lstrip("#")
        return {"중식":result[:2],"석식":result[2:]}
        

