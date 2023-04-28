

import numpy as np
import pandas as pd
import re
import json


from konlpy.tag import Okt
okt = Okt()




prompt = '''
*알러지유발식품: 양지쌀국수(해당사항없음),닭갈비(해당사항없음),망고샐러드(해당사항없음),포기김치(새우),야쿠르트(유제품)'''

string = re.sub('[^a-zA-Z0-9ㄱ-힣\\s]', '', prompt)

string = string.replace('\n', '')

string=string.replace('해당사항없음','')

print(string)

tokens = okt.pos(string)


for i in tokens:
    if i[1]=="Noun":
        print(i)


string = prompt.replace("*알러지유발식품: ","").strip()
pattern = re.compile(r'\([^)]*\)')

string=re.sub(pattern, '',string)

print(string.split(","))


