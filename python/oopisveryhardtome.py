import urllib.request
from bs4 import BeautifulSoup
import re
from enum import Enum

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


a=Dodam_or_School_Cafeteria("2","20230501")

a.get_menu()

print(a)