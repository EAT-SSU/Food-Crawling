import urllib.request
from bs4 import BeautifulSoup
import re
from enum import Enum
import pandas as pd
from html_table_parser import parser_functions as parser

class Restaurant(Enum):
    DODAM=1
    DOMITORY=2
    FOOD_COURT=3
    SNACK_CORNER=4
    HAKSIK=5
    THE_KITCHEN=6

class Dodam_or_School_Cafeteria:
    def __init__(self,restaurant_type:Restaurant,date) -> None:
        self.restaurant_type=restaurant_type
        self.date=date
        self.menu=None
        self.soup=None
    
    def todaysoup(self): # 1이면 학생식당, 2이면 도담식당
        webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={self.restaurant_type}&sdt={self.date}')
        soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')

        self.soup=soup

    def find_all_menu_nm_dict(self) ->dict:
        tr_list=self.soup.find_all('tr')
        menu_nm_dict=dict()

        for tr_tag in tr_list: # tr_tag는 tr과 그 하위 태그인 Beautifulsoup 객체
            td_tag = tr_tag.find('td', {'class': 'menu_nm'})
            if td_tag:
                menu_nm_dict[td_tag.text]=tr_tag
                
        return menu_nm_dict


    def find_food(self,value):
        elements = value.find(text=lambda text: text and text.startswith("*알러지유발식품:"))
        # iswell_newline=elements.next_element.string.startswith("*원산지")
        # print(elements)
        # print(elements.next_element,type(elements.next_element))

        iswell_newline=elements.next_element.text.startswith("*원산지")


        # 예외처리: 현재 크롤링 로직은 *알러지유발식품:~ 이것이 한 Tag 객체에 text로 존재할 것을 가정하나, 만약 한 태그 내에 알러지유발식품에 대한 전체 문자열이 없는 경우(다음 div에 메뉴에 대한 정보가 있는 경우, 아마도 사이트에서 개행을 하면 다른 div로 가는듯) 다음 태그인 원산지가 나올때가 문자열을 접합한다.

        if iswell_newline is False: 
            menu=str(elements)
            elements=elements.next_element
            while iswell_newline is False:
                iswell_newline=elements.find_next_sibling("div").text.startswith("*원산지")
                menu+=elements.text
                elements=elements.find_next_sibling("div")
            menu=menu.replace("*알러지유발식품:","").strip()
            return menu

        menu=elements.replace("*알러지유발식품:","").strip()

        return menu

    def parse_allergy(self,elements):
        
        pattern = re.compile(r'\([^)]*\)')
        td=re.sub(pattern, '',elements)
        td=td.split(",")

        return td
    
    def get_menu(self):
        self.todaysoup()
        menu_nm_dict=self.find_all_menu_nm_dict()
        final_dict=dict()
        for key,value in menu_nm_dict.items():
            food=self.find_food(value)
            k=self.parse_allergy(food)
            final_dict[key]=k
        self.menu=final_dict
        return self.menu
    
    def __str__(self) -> str:
        return f"{self.menu}"

class Dormitory:
    def __init__(self,year,month,day) -> None:
        webpage=urllib.request.urlopen(f'https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear={year}&gmonth={month}&gday={day}')
        self.soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')
        self.table=None

    def refine_table(self):
        table_tag=self.soup.find("table","boxstyle02")
        table=parser.make2d(table_tag)
        df=pd.DataFrame(table)
        dt2 = df.rename(columns=df.iloc[0])
        dt3 = dt2.drop(dt2.index[0])
        dt3["조식"] = dt3["조식"].str.split("\r\n")
        dt3["중식"] = dt3["중식"].str.split("\r\n")
        dt3["석식"] = dt3["석식"].str.split("\r\n")
        del dt3["중.석식"]

        dt3 = dt3.set_index('날짜')

        self.table=dt3

    def get_table(self):
        for index,rows in self.table.iterrows():
            for col_name in self.table.columns:
                # print(index, col_name, rows[col_name])
                print(f'{index},{col_name},{rows[col_name]}')



    

