import urllib.request
from bs4 import BeautifulSoup
import re
import pandas as pd
from html_table_parser import parser_functions as parser

webpage=urllib.request.urlopen('https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear=2023&gmonth=01&gday=26')


soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')
table_tag=soup.find("table","boxstyle02")

table=parser.make2d(table_tag)
df=pd.DataFrame(table)
dt2 = df.rename(columns=df.iloc[0])
dt3 = dt2.drop(dt2.index[0])

dt3["조식"] = dt3["조식"].str.split("\r\n")
dt3["중식"] = dt3["중식"].str.split("\r\n")
dt3["석식"] = dt3["석식"].str.split("\r\n")
dt3["중.석식"] = dt3["중.석식"].str.split("\r\n")

a=dt3.to_json(force_ascii=False,orient="table")

print(a)
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


        
        
df=pd.DataFrame(table)



