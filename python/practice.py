from bs4 import BeautifulSoup
import requests
import json
import logging
import openai
import os
from dotenv import load_dotenv
import time


class HolidayError(Exception):
    def __init__(self,date):
        super().__init__(f'The restaurant is closed on this date {date}')

class NetworkError(Exception):
    def __init__(self):
        super().__init__('While sending requests to ChatGPT, All retrial are failed.')






load_dotenv()

# OpenAI API 인증
openai.api_key = os.environ.get("GPT_API_KEY")


# # AWS 리전 및 자격 증명을 설정합니다.
# region_name = 'ap-northeast-2'
# aws_access_key_id = 'your-access-key-id'
# aws_secret_access_key = 'your-secret-access-key'

# client = boto3.client('logs', region_name=region_name, aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)

# 로거 인스턴스 생성
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 파일 핸들러 생성 및 설정
file_handler = logging.FileHandler('../data/my_log.log')
file_handler.setLevel(logging.DEBUG)

# 콘솔 핸들러 생성 및 설정 (표준 출력에 로그를 출력)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# 로그 포맷 설정
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 핸들러를 로거에 추가
logger.addHandler(file_handler)
logger.addHandler(console_handler)

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

student_lunch_1 = '''
[뚝배기코너]

뚝배기부대찌개*당면사리 - 5.0
Sausage jjigae hot pot*Glass noodles

고구마맛탕
수수밥
깍두기
'''

def practice_student_restarant(date:str):

    res = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd=1&sdt={date}")

    soup = BeautifulSoup(res.content, "html.parser")

    if soup.find(text="오늘은 쉽니다."):
        logger.error(f"The date is holiday. {date}")
        raise HolidayError(date)

    tr_list = soup.find_all('tr')
    menu_nm_dict = dict()

    for tr_tag in tr_list:  # tr_tag는 tr과 그 하위 태그인 Beautifulsoup 객체
        td_tag = tr_tag.find('td', {'class': 'menu_nm'})
        if td_tag:
            menu_nm_dict[td_tag.text] = tr_tag

    menu_nm_dict = strip_string_from_html(menu_nm_dict)

    res_from_ai = chat_with_gpt_student_restaurant(menu_nm_dict)

    refine_res = {
        "restaurant":"학생식당",
        "date": date,
        "menu":res_from_ai
    }

    logger.debug(f"{__name__} final result is {refine_res}")


    return refine_res


def practice_dodam(date:str):

    res = requests.get(f"http://m.soongguri.com/m_req/m_menu.php?rcd=2&sdt={date}")

    soup = BeautifulSoup(res.content, "html.parser")

    if soup.find(text="오늘은 쉽니다."):
        logger.error(f"The date is holiday. {date}")
        raise HolidayError(date)

    tr_list = soup.find_all('tr')
    menu_nm_dict = dict()

    for tr_tag in tr_list:  # tr_tag는 tr과 그 하위 태그인 Beautifulsoup 객체
        td_tag = tr_tag.find('td', {'class': 'menu_nm'})
        if td_tag:
            menu_nm_dict[td_tag.text] = tr_tag

    # print(menu_nm_dict)

    menu_nm_dict = strip_string_from_html(menu_nm_dict)

    # logger.debug(menu_nm_dict)

    res_from_ai = chat_with_gpt_dodam(menu_nm_dict)

    refine_res = {
        "restaurant":"도담식당",
        "date": date,
        "menu":res_from_ai
    }

    logger.debug(f"{__name__} final result is {refine_res}")

    return refine_res



    # logger.debug(menu_nm_dict)

def strip_string_from_html(menu_dict):

    for key, value in menu_dict.items():
        new_text = ""

        for text in value.stripped_strings:
            new_text+=f"{text}/n"
        menu_dict[key] = new_text
    
    return menu_dict

def chat_with_gpt_dodam(today_mnu_dict) -> dict:
    setup_messages = [
        {"role": "system", "content": "너는 메인메뉴와 사이드메뉴를 구분하는 함수의 역할을 맡았다. input값에서 메인 메뉴와 사이드 메뉴를 구분해야해. list에는 input값에서의 메인 메뉴만 골라낸 요소들의 이름이 들어가. 만약 동일한 메인메뉴가 있다면 한 개만 리스트에 넣어. 그외에 부가적인 설명은 하지 않고 오직 json을 반환해."},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 배열을 만들고 반환해줘.:{dodam_lunch_1}"},
        {"role": "assistant", "content": '["오꼬노미돈까스","웨지감자튀김*케찹"]'},
    ]

    max_retries = 3
    delay_seconds = 5

    for key, value in today_mnu_dict.items():
        retries = 0
        while retries < max_retries:
            try:
                setup_messages.append({"role": "user", "content": f"input은 바로 이거야. 여기서 메뉴를 골라내어 list을 반환해줘.:{value}"})

                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=setup_messages
                )

                today_mnu_dict[key] = json.loads(response['choices'][0]['message']['content'])

                setup_messages.pop()
                break  # 성공한 경우 반복문 종료
            except openai.error.RateLimitError as ai_e:  # API 요청 제한에 도달한 경우
                logging.error(f"API Request Cap Reached. {ai_e}")
                # 재시도 대기 시간만큼 대기
                time.sleep(delay_seconds)
                retries += 1
            except KeyError as key_e:  # chatgpt response가 안와서 dict에 key값이 없음
                logging.error(f"KeyError occurred. {key_e}")
                time.sleep(delay_seconds)
                retries += 1
            except json.decoder.JSONDecodeError as json_e:
                logging.error(f"Request is failed. {json_e}")
                time.sleep(delay_seconds)
                retries += 1
        
        if retries >= max_retries:
            logging.error(f"All retrials are failed.")
            raise NetworkError

    return today_mnu_dict

def chat_with_gpt_student_restaurant(today_mnu_dict) -> dict:
    setup_messages = [
        {"role": "system", "content": "너는 메인메뉴와 사이드메뉴를 구분하는 함수의 역할을 맡았다. 너는 메인메뉴가 담긴 list만을 반환하는 함수의 역할을 맡았다. input값에서 메인 메뉴와 사이드 메뉴를 구분해야해. list에는 input값에서의 메인 메뉴만 골라낸 요소들의 이름이 들어가. 만약 동일한 메인메뉴가 있다면 한 개만 리스트에 넣어. 그외에 부가적인 설명은 하지 않고 오직 json을 반환해."},
        {"role": "user", "content": f"input은 바로 이거야. 여기서 메인 메뉴를 골라내어 배열을 만들고 반환해줘.:{student_lunch_1}"},
        {"role": "assistant", "content": '["뚝배기부대찌개*당면사리"]'},
    ]

    max_retries = 3
    delay_seconds = 5

    for key, value in today_mnu_dict.items():
        retries = 0
        while retries < max_retries:
            try:
                setup_messages.append({"role": "user", "content": f"input은 바로 이거야. 여기서 메인 메뉴를 골라내어 list을 반환해줘.:{value}"})

                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=setup_messages
                )

                today_mnu_dict[key] = json.loads(response['choices'][0]['message']['content'])

                setup_messages.pop()
                break  # 성공한 경우 반복문 종료
            except openai.error.RateLimitError as ai_e:  # API 요청 제한에 도달한 경우
                logging.error(f"API Request Cap Reached. {ai_e}")
                # 재시도 대기 시간만큼 대기
                time.sleep(delay_seconds)
                retries += 1
            except KeyError as key_e:  # chatgpt response가 안와서 dict에 key값이 없음
                logging.error(f"KeyError occurred. {key_e}")
                time.sleep(delay_seconds)
                retries += 1
            except json.decoder.JSONDecodeError as json_e:
                logging.error(f"Request is failed. {json_e}")
                time.sleep(delay_seconds)
                retries += 1
        
        if retries >= max_retries:
            logging.error(f"All retrials are failed.")
            raise NetworkError

    return today_mnu_dict



if __name__ == "__main__":

    practice_student_restarant("20230917")


