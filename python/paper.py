import urllib.request
from bs4 import BeautifulSoup
import re

restaurantType=1
day=20221101


webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={restaurantType}&sdt={day}')
soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')

# print(soup.text)
a=soup.find(text=re.compile("^뚝"))

        return(soup.find(text=re.compile("^뚝")).strip())


print(a.text)