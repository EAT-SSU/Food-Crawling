import urllib.request
from bs4 import BeautifulSoup
import re

webpage=urllib.request.urlopen('https://ssudorm.ssu.ac.kr:444/SShostel/mall_main.php?viewform=B0001_foodboard_list&gyear=2023&gmonth=01&gday=26')
soup:BeautifulSoup = BeautifulSoup(webpage, 'html.parser')
soup.next_element
a=soup.find_all(string=re.compile("\d{4}-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01])"))
soup.next

for i in a:
    print(i.next_sibling.string)
print(len(a))


