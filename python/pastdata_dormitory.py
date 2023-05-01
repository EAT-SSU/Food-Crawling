import urllib.request
from bs4 import BeautifulSoup
import re
import pandas as pd
from html_table_parser import parser_functions as parser
from datetime import date, timedelta
import os

start = date(2020, 1, 2)  # 시작일자
end = date(2023, 5, 1)  # 종료일자
step = timedelta(weeks=1)  # 1주일씩 증가

new_path = "C:/Users/rover0811/Desktop/Github/food-crawling/python"
os.chdir(new_path)


with open(f'../data/dormitory_{start.strftime("%Y%m%d")}~{end.strftime("%Y%m%d")}.csv', 'w') as f:  # 파일을 열고 쓰기 모드로 엽니다

    while start <= end:
        month = start.month
        day = start.day
        year=start.year
        # url = f'https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear=2023&gmonth={month}&gday={day}'

        webpage=urllib.request.urlopen(f'https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear={year}&gmonth={month}&gday={day}')


        soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')
        table_tag=soup.find("table","boxstyle02")

        table=parser.make2d(table_tag)
        df=pd.DataFrame(table)
        dt2 = df.rename(columns=df.iloc[0])
        dt3 = dt2.drop(dt2.index[0])

        dt3["조식"] = dt3["조식"].str.split("\r\n")
        dt3["중식"] = dt3["중식"].str.split("\r\n")
        dt3["석식"] = dt3["석식"].str.split("\r\n")

        del dt3["중.석식"]

        dt3 = dt3.set_index('날짜')

        for index,rows in dt3.iterrows():
            for col_name in dt3.columns:
                # print(index, col_name, rows[col_name])
                f.write(f'"{index}","{col_name}","{rows[col_name]}"\n')  # 결과를 파일에 씁니다

        start += step  # 날짜 증가





# a=dt3.to_json(force_ascii=False,orient="table")

# print(a)


# for lowindex,low in enumerate(table):
#     if lowindex==0:
#         continue
#     for index,value in enumerate(low):
#         if (index==0):
#             day=value
#             a[day]={"조식":"","중식":"","석식":"","중.석식":""}
#         elif(index==1):
#             a[day]["조식"]=value.split("\r\n")
#         elif(index==2):
#             a[day]["중식"]=value.split("\r\n")
#         elif(index==4):
#             a[day]["중.석식"]=value.split("\r\n")




