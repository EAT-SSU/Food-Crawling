import urllib.request
from bs4 import BeautifulSoup
import re
from typing import Optional
from fastapi import FastAPI
from datetime import datetime
from typing import *

app = FastAPI()

'''
    ?    rcd=2  &   sdt=20230206
    rcd=1 -> 학생식당
    rcd=2 -> 숭실도담식당

    sdt   -> 날짜

'''
@app.get("/foods/{day}/{restaurantType}",description="도담식당과 학생식당의 메뉴를 받아오는 api입니다. restaurantType={1:학생식당,2:숭실도담식당} day={yyyymmdd} 도담식당이랑 학생식당만 가능합니다.")
def getTodayMenu(restaurantType:int, date:str) -> Union[str, Dict[str, List[str]], None]:
    """
    Fetches the menu for a given date and restaurant type.

    Parameters:
        - restaurantType (int): The type of the restaurant to query. 
          Possible values are 1 (학생식당), 2 (숭실도담식당), or 3 (기숙사 식당).
        - date (str): The date in the format 'yyyymmdd' for which to fetch the menu.

    Returns:
        - str: A message indicating that the restaurant is closed on weekends, if the requested date falls on a weekend.
        - Dict[str, List[str]]: A dictionary containing the menu for both lunch and dinner (중식 and 석식) 
          for the requested date and restaurant type, if the requested restaurant is '숭실도담식당'.
        - None: If the requested restaurant type is not supported.

    Note:
        This function scrapes the mobile website of 숭실대학교(Soongsil University) cafeteria to fetch the menu.
        Therefore, the function may fail if the website structure changes or if the website is down.
    """
        
    webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={restaurantType}&sdt={date}')
    soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')

    inputDate = datetime.strptime(date,'%Y%m%d')
    if (inputDate.weekday()==5 or inputDate.weekday()==6):
        return "주말은 쉽니다"
    
    if (restaurantType==1): #학생식당
        json={}
        json["중식1"]=soup.find(text=re.compile("^뚝")).strip()
        json["식당"]="학생식당"
        json["날짜"]=date
        return(json)
        #일단 학생식당 부분은 pass
    elif (restaurantType==2): #도담식당
        json={}
        json["식당"]="도담식당"
        json["날짜"]=date
        result=soup.find_all("tr")
        for i in result:
            if (i.td.string=="중식1"):
                # json["중식"]=[ k.strip().lstrip("#") for k in i.find_all(text=re.compile("#.*"))] # 2022년도 규칙 #뒤에 메뉴
                json["중식1"]=[k.next_element.text for k in i.find_all(text=re.compile("★.*"))] #2023년도 규칙 ★다음 요소에 메뉴
                # json["중식"]=[k.text for k in i.find_all('font', {'color': '#ff9900'})] #2023년도 규칙 폰트 컬러가 #ff9900
            elif (i.td.string=="중식4"):
                json["중식4"]=[k.next_element.text for k in i.find_all(text=re.compile("★.*"))]


            elif(i.td.string=="석식1"):
                # json["석식"]=[ k.strip().lstrip("#") for k in i.find_all(text=re.compile("#.*"))]
                json["석식1"]=[k.next_element.text for k in i.find_all(text=re.compile("★.*"))]

        return json
    elif (restaurantType==3): #기숙사 식당
        pass
