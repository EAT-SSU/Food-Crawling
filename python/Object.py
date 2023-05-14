import requests
from bs4 import BeautifulSoup
import re
from enum import Enum
import pandas as pd
from html_table_parser import parser_functions as parser
from datetime import date,datetime
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel
from constant import SOONGGURI_HEADERS

class Menu(BaseModel):
    date: str
    restaurant_type: str
    menu: dict=dict()

class Restaurant(ABC):

    def __init__(self,date,restaurant_type) -> None:
        super().__init__()
        self.date=date
        self.restaurant_type=restaurant_type
        self.soup=None
        self.menu_rows=None
        self.menu=Menu(date,restaurant_type)

    def __str__(self) -> str:
        return f"{self.menu}"

    def get_soup(self):
        webpage=requests.get(f'http://m.soongguri.com/m_req/m_menu.php?rcd={self.restaurant_type}&sdt={self.date}',headers=SOONGGURI_HEADERS)
        soup:BeautifulSoup = BeautifulSoup(webpage.content, 'html.parser')

        self.soup=soup

    def get_menu_rows(self):
        tr_list=self.soup.find_all('tr')
        menu_nm_dict=dict()

        for tr_tag in tr_list: # tr_tag는 tr과 그 하위 태그인 Beautifulsoup 객체
            td_tag = tr_tag.find('td', {'class': 'menu_nm'})
            if td_tag:
                menu_nm_dict[td_tag.text]=tr_tag
                
        self.menu_rows=menu_nm_dict

    @abstractmethod
    def parse_menu(self):
        pass

    def get_menu(self):
        self.get_soup()
        self.get_menu_rows()

        for k,v in self.menu_rows.items():
            self.parse_menu(k,v)

        return self.menu

class Dodam(Restaurant):

    def __init__(self,date) -> None:
        super().__init__(restaurant_type=2,date=date)
    
    def parse_menu(self):
        pass
    

class School_Cafeteria(Restaurant):

    def __init__(self,date) -> None:
        super().__init__(restaurant_type=1,date=date)
        self.get_menu()
    
    def parse_menu(self):
        pass
    
    

class Dodam_or_School_Cafeteria:
    def __init__(self,restaurant_type,date) -> None:
        self.restaurant_type=restaurant_type
        self.date=date
        self.menu=None
        self.soup=None
    
    def todaysoup(self): # 1이면 학생식당, 2이면 도담식당
        # webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={self.restaurant_type}&sdt={self.date}')
        webpage=requests.get(f'http://m.soongguri.com/m_req/m_menu.php?rcd={self.restaurant_type}&sdt={self.date}',headers=SOONGGURI_HEADERS)
        soup:BeautifulSoup = BeautifulSoup(webpage.content, 'html.parser')
        
        self.soup=soup

    def find_all_menu_nm_dict(self) ->dict:
        tr_list=self.soup.find_all('tr')
        menu_nm_dict=dict()

        for tr_tag in tr_list: # tr_tag는 tr과 그 하위 태그인 Beautifulsoup 객체
            td_tag = tr_tag.find('td', {'class': 'menu_nm'})
            if td_tag:
                menu_nm_dict[td_tag.text]=tr_tag
                
        return menu_nm_dict


    def find_food(self,value) ->list or str:
        '''
            value: Beautifulsoup 객체, 하나의 tr 객체이다. 즉 하나의 행 html 객체이다. ex) 중식1 tr 객체, 중식2 tr 객체, 석식1 tr 객체
            return: 알러지 유발 식품 정보를 담은 문자열 또는 메뉴 정보를 담은 리스트 혹은 문자열
                    1. 알러지유발식품으로 잘 찾을 시에는 문자열을 리턴하고 parse_allergy로 가서 파싱이 됨
                    2. 만약 못찾을시 ★으로 시작하는 문자열을 찾고 별을 제거하고 split한 리스트를 바로 final_dict에 할당

            실질적으로 크롤링 로직 수정시 이 함수만 건드리면 됨
        '''

        try:
            elements = value.find(text=lambda text: text and text.startswith("*알러지유발식품:"))
            # iswell_newline=elements.next_element.string.startswith("*원산지")
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
        except:
            # if elements is None: #예외 <br> 태그로 인해서 알러지로 실패할 시 ★을 찾는 방식으로 대체
            menu=value.find_all(text=re.compile("★.*"))
            menu=[i.lstrip("★") for i in menu]
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
            print(type(food))
            if type(food) is str:
                k=self.parse_allergy(food)
            elif type(food) is list:
                k=food
            print(k)
            final_dict[key]=k
        self.menu=final_dict
        return self.menu
    
    def __str__(self) -> str:
        return f"{self.menu}"

class Dormitory:
    def __init__(self,date) -> None:
        date = datetime.strptime(date,'%Y%m%d')
        # webpage=urllib.request.urlopen(f'https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear={date.year}&gmonth={date.month}&gday={date.day}')
        webpage=requests.get(f'https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear={date.year}&gmonth={date.month}&gday={date.day}')
        self.soup:BeautifulSoup = BeautifulSoup(webpage.content, 'html.parser')
        self.table=None
        self.dict=dict()

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
            self.dict[index]=dict()
            for col_name in self.table.columns:
                # print(f'{index},{col_name},{rows[col_name]}')
                self.dict[index][col_name]=rows[col_name]

    def __str__(self) -> str:
        return self.dict
    



    

