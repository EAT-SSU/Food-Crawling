from typing import Optional
from fastapi import FastAPI,status
from typing import *
from Object import Dodam_or_School_Cafeteria
from Object import Dormitory

# from fastapi.responses import JSONResponse
# from pydantic import BaseModel
import sys
sys.path.append("/app/python/")


# class SoongsilMenuModel(BaseModel):
#     date: Union[str,None]= None
#     restaurantType: Union[str,None] = None
#     lunch: Union[dict,list, None] = None
#     dinner: Union[list, None] = None

app = FastAPI()

'''
    ?    rcd=2  &   sdt=20230206
    rcd=1 -> 학생식당
    rcd=2 -> 숭실도담식당

    sdt   -> 날짜

'''
# @app.get("/foods/{day}/{restaurantType}",
#         description="도담식당과 학생식당의 메뉴를 받아오는 api입니다. restaurantType={1:학생식당,2:숭실도담식당} day={yyyymmdd} 도담식당이랑 학생식당만 가능합니다.")
# def getTodayMenu(restaurantType:int, date:str):
#     """
#     Fetches the menu for a given date and restaurant type.

#     Parameters:
#         - restaurantType (int): The type of the restaurant to query. 
#           Possible values are 1 (학생식당), 2 (숭실도담식당), or 3 (기숙사 식당).
#         - date (str): The date in the format 'yyyymmdd' for which to fetch the menu.

#     Returns:
#         - str: A message indicating that the restaurant is closed on weekends, if the requested date falls on a weekend.
#         - Dict[str, List[str]]: A dictionary containing the menu for both lunch and dinner (중식 and 석식) 
#           for the requested date and restaurant type, if the requested restaurant is '숭실도담식당'.
#         - None: If the requested restaurant type is not supported.

#     Note:
#         This function scrapes the mobile website of 숭실대학교(Soongsil University) cafeteria to fetch the menu.
#         Therefore, the function may fail if the website structure changes or if the website is down.
#     """
        
#     soongguri_webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={restaurantType}&sdt={date}')
#     soup:BeautifulSoup = BeautifulSoup(soongguri_webpage, 'html.parser')

#     inputDate = datetime.strptime(date,'%Y%m%d')
#     if (inputDate.weekday()==5 or inputDate.weekday()==6):
#         return JSONResponse(status_code=status.HTTP_404_NOT_FOUND,content=SoongsilMenuModel(date=date).dict())
    
#     if (restaurantType==1): #학생식당
#         school_cafeteria_lunch=[soup.find(text=re.compile("^뚝")).strip()]
#         return JSONResponse(status_code=status.HTTP_200_OK,content=SoongsilMenuModel(date=date,restaurantType="학생식당",lunch=school_cafeteria_lunch).dict())
#     elif (restaurantType==2): #도담식당
#         tr_result=soup.find_all("tr")
#         dodam_restaurant_model=SoongsilMenuModel(lunch=dict(),restaurantType="도담식당",date=date)
#         for i in tr_result:
#             if (i.td.string=="중식1"):
#                 # json["중식"]=[ k.strip().lstrip("#") for k in i.find_all(text=re.compile("#.*"))] # 2022년도 규칙 #뒤에 메뉴
#                 dodam_restaurant_model.lunch["중식1"]=[k.next_element.text for k in i.find_all(text=re.compile("★.*"))] #2023년도 규칙 ★다음 요소에 메뉴
#             elif (i.td.string=="중식4"):
#                 dodam_restaurant_model.lunch["중식4"]=[k.next_element.text for k in i.find_all(text=re.compile("★.*"))] #2023년도 규칙 ★다음 요소에 메뉴
#             elif(i.td.string=="석식1"):
#                 # json["석식"]=[ k.strip().lstrip("#") for k in i.find_all(text=re.compile("#.*"))]
#                 dodam_restaurant_model.dinner=[k.next_element.text for k in i.find_all(text=re.compile("★.*"))]
#         return JSONResponse(status_code=status.HTTP_200_OK,content=dodam_restaurant_model.dict())

#     elif (restaurantType==3): #기숙사 식당
#         pass

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




    
        