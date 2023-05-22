import openai
import os
from dotenv import load_dotenv


load_dotenv()

# OpenAI API 인증
openai.api_key = os.environ.get("GPT_API_KEY")

dodam_lunch_1='''[대면배식 코너]

★오꼬노미돈까스
★웨지감자튀김*케찹

오꼬노미돈까스, 웨지감자튀김*케찹 - 6.0
(Okonomi tonkatsu, Wedge french fries*ketchup)
파인애플샐러드
후리가케밥
얼큰어묵국
깍두기
야쿠르트

*알러지유발식품:오꼬노미돈까스(돈육,계란,빵가루),웨지감자튀김&케찹(토마토),얼큰어묵국(밀),깍두기(새우젓),야쿠르트(유제품)
*원산지 : 오꼬노미돈까스(돈등심/국내산,계란/국산),깍두기(무&고추분/국내산)'''

dodam_lunch_4='''[웰빙 코너]

★오징어비빔밥
★계란후라이

오징어비빔밥, 계란후라이 - 6.0
(Squid bibimbap, Fried eggs)
고소한참기름
약고추장
우거지된장국
열무김치
야쿠르트


*알러지유발식품:계란후라이(계란),우거지국(대두),야쿠르트(유제품)
*원산지 : 오징어비빔밥(오징어/칠레산),계란후라이(계란/국내산),우거지국(대두/외국산),열무김치(열무&고추분/국내산)'''

dodam_dinner_1='''[대면배식 코너]

★생고기김치찌개
★새우젓계란찜

생고기김치찌개, 새우젓계란찜 - 6.0
(Kimchi stew with raw meat, Steamed salted shrimp with egg)
한식잡채
도시락김
찰현미밥
야쿠르트'''



school_lunch_1='''
	
[뚝배기코너]

뚝배기콘소시지나폴리탄파스타 - 5.0
Ttukbaegi Corn Sausage National pasta

감자고로케
후리가케주먹밥
오이피클
요구르트

*알러지유발식품:
*원산지:
'''

school_lunch_2='''
	
[덮밥코너]

덮밥 위에 골라 먹는 토핑! - 5.0
고추잡채, 비프바베큐, 치킨데리야끼

-고추잡채덮밥
Rice with red pepper japchae
-비프바베큐덮밥
Rice with Beef barbecue
-치킨데리야끼덮밥
Rice with chicken deriyaki

계란후라이
감자고로케
유부된장국
단무지

*알러지유발식품:
*원산지:
'''
# ChatGPT 모델과 대화하기 위한 함수
def chat_with_gpt_dodam(today):
    response=openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": "너는 list만을 반환하는 함수의 역할을 맡았다. input값에서 중요한 메뉴만을 골라서 list형태로 반환해. list에는 input값에서의 메인 메뉴만 골라낸 요소들의 이름이 들어가. 그외에 부가적인 설명은 하지 않고 오직 json을 반환해."},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 배열을 만들고 반환해줘.:{dodam_lunch_1}"},
        {"role": "assistant", "content": '["오꼬노미돈까스","웨지감자튀김*케찹"]'},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 list을 반환해줘.:{today}"},
    ]
    )

    if response and response.choices:
        return response.choices[0].message.content.strip()
    else:
        return ""

def chat_with_gpt_school_cafeteria(today):
    response=openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": "너는 list만을 반환하는 함수의 역할을 맡았다. input값에서 중요한 메뉴만을 골라서 list형태로 반환해. list에는 input값에서의 메인 메뉴만 골라낸 요소들의 이름이 들어가. 그외에 부가적인 설명은 하지 않고 오직 json을 반환해."},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 배열을 만들고 반환해줘.:{school_lunch_1}"},
        {"role": "assistant", "content": '["뚝배기콘소시지나폴리탄파스타"]'},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 배열을 만들고 반환해줘.:{school_lunch_2}"},
        {"role": "assistant", "content": '["고추잡채덮밥","비프바베큐덮밥","치킨데리야끼덮밥"]'},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 list을 반환해줘.:{today}"},
    ]
    )

    if response and response.choices:
        return response.choices[0].message.content.strip()
    else:
        return ""


