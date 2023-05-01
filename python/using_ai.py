import re
import json
from bs4 import BeautifulSoup
import urllib3 as urllib


soongguri_webpage=urllib.request.urlopen(f'http://m.soongguri.com/m_req/m_menu.php?rcd={2}&sdt={20230501}')
soup:BeautifulSoup = BeautifulSoup(soongguri_webpage, 'html.parser')


print(soup.text)


from konlpy.tag import Okt
okt = Okt()
# tokens = okt.pos(string)


# for i in tokens:
#     if i[1]=="Noun":
#         print(i)

prompt = '''
*알러지유발식품: 양지쌀국수(해당사항없음),닭갈비(해당사항없음),망고샐러드(해당사항없음),포기김치(새우),야쿠르트(유제품)'''

string = re.sub('[^a-zA-Z0-9ㄱ-힣\\s]', '', prompt)

string = string.replace('\n', '')

string=string.replace('해당사항없음','')

print(string)


string = prompt.replace("*알러지유발식품: ","").strip()
pattern = re.compile(r'\([^)]*\)')

string=re.sub(pattern, '',string)

print(string.split(","))


