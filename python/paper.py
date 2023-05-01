import urllib.request
from bs4 import BeautifulSoup
import re


def todaysoup(restaurantType,day): # 1이면 학생식당, 2이면 도담식당
    webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={restaurantType}&sdt={day}')
    soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')

    return soup

def find_all_menu_nm_dict(soup) ->list:
    tr_list=soup.find_all('tr')
    menu_nm_dict=dict()

    for tr_tag in tr_list: # tr_tag는 tr과 그 하위 태그인 Beautifulsoup 객체
        td_tag = tr_tag.find('td', {'class': 'menu_nm'})
        if td_tag:
            menu_nm_dict[td_tag.text]=tr_tag
            
    return menu_nm_dict


def find_food(soup:BeautifulSoup):
    elements = soup.find(text=lambda text: text and text.startswith("*알러지유발식품:"))
    # element = element.replace("*알러지유발식품:","").strip()
    menu=elements.replace("*알러지유발식품:","").strip()

    return menu

def parse_allergy(elements):
    
    pattern = re.compile(r'\([^)]*\)')
    td=re.sub(pattern, '',elements)
    td=td.split(",")

    return td


soup=todaysoup("1","20230501")
menu_nm_dict=find_all_menu_nm_dict(soup)
final_dict=dict()
for key,value in menu_nm_dict.items():
    a=find_food(value)
    k=parse_allergy(a)
    final_dict[key]=k

print(final_dict)


