import requests
import json
from Object import Dodam, School_Cafeteria, NoMenuError, Dormitory
import sentry_sdk
from sentry_sdk.crons import monitor
from dotenv import load_dotenv
import os
import threading

from datetime import datetime,timedelta
import pytz

seoul_timezone = pytz.timezone('Asia/Seoul')
current_time = datetime.now(seoul_timezone)
today = current_time.date().strftime("%Y%m%d")

load_dotenv()


sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production,
    traces_sample_rate=1.0,
)


def send_slack_message(api_response):
    """
    Slack Incoming Webhooks를 사용하여 메시지를 보내는 함수
    :param message: 보낼 메시지
    :param slack_webhook_url: Slack Incoming Webhooks URL
    :return: 성공 여부
    """
    slack_webhook_url = os.environ.get("SLACK_URL")

    if api_response['restaurant_type'] == '1':
        api_response['restaurant_type'] = "학생식당"
    elif api_response['restaurant_type'] == '2':
        api_response['restaurant_type'] = "도담식당"
    elif api_response['restaurant_type'] == '3':
        api_response['restaurant_type'] = "기숙사식당"


    text = f"날짜: {api_response['date']}\n식당: {api_response['restaurant_type']}\n메뉴: {api_response['menu']}"
    body = {"channel": "#api-notification", "username": "학식봇",
            "text": text, "icon_emoji": ":ghost:"}
    response = requests.post(slack_webhook_url, data=json.dumps(body))
    if response.status_code != 200:
        raise ValueError('Slack message sending failed')
    return True



@monitor(monitor_slug='qq')
def testing_Dodam(date):
    try:
        api_response = Dodam(date=date).get_menu()
        print(api_response, type(api_response))
        send_slack_message(api_response)

    except Exception as e:
        sentry_sdk.capture_exception(e)


@monitor(monitor_slug='qq')
def testing_School_Cafeteria(date):
    try:
        api_response = School_Cafeteria(date=date).get_menu()
        print(api_response, type(api_response))
        send_slack_message(api_response)

    except Exception as e:
        sentry_sdk.capture_exception(e)

@monitor(monitor_slug='qq')
def testing_Dormitory(date):
    try:
        api_responses = Dormitory(date=date).get_menu()
        print(api_responses, type(api_responses))

        threads = []

    
        for response in api_responses:
            thread = threading.Thread(target=send_slack_message, args=(response,))
            threads.append(thread)
            thread.start()


    # # 모든 스레드가 종료될 때까지 대기
    # for thread in threads:
    #     thread.join()
        
    except Exception as e:
        sentry_sdk.capture_exception(e)



# testing_Dodam()
# # testing_School_Cafeteria()

if __name__=="__main__":
    '''
        TODO: 이 부분이 CRON되는 곳.
    '''


    @monitor(monitor_slug='qq')
    def testing_all(date):
        testing_Dodam(date)
        testing_School_Cafeteria(date)

        
    now=current_time.date()
    now_weekday=now.weekday() # Return day of the week, where Monday == 0 ... Sunday == 6.

    date_list=[]

    if 0 <= now_weekday <= 5: # 이 파일을 실행한 시기가 월요일부터, 토요일까지라면 이번주의 날짜를 받아오고
        start_of_this_week = now - timedelta(days=now_weekday)
        for i in range(6):
            date_list.append(start_of_this_week.strftime("%Y%m%d"))
            start_of_this_week += timedelta(days=1)
    elif now_weekday==6: # 이 파일을 실행한 시기가 일요일이라면 다음주의 날짜(월, 화, 수, 목, 금, 토)를 받아오기
        start_of_next_week = now + timedelta(days=(7 - now_weekday))
        for i in range(6):
            date_list.append(start_of_next_week.strftime("%Y%m%d"))
            start_of_next_week += timedelta(days=1)


    
    threads = []

    testing_Dormitory(date=date_list[0])
    
    for date in date_list:
        thread = threading.Thread(target=testing_all, args=(date,))
        threads.append(thread)
        thread.start()


    # 모든 스레드가 종료될 때까지 대기
    for thread in threads:
        thread.join()
    

    


    

        



    







