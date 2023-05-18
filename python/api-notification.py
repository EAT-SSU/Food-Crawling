import requests
import json
from Object import Dodam,School_Cafeteria
import sentry_sdk
from sentry_sdk.crons import monitor
# from fastapi.encoders import jsonable_encoder
from dotenv import load_dotenv
import os



from datetime import datetime
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
    slack_webhook_url=os.environ.get("SLACK_URL")

    if api_response['restaurant_type']=='1':api_response['restaurant_type']="학생식당"
    elif api_response['restaurant_type']=='2':api_response['restaurant_type']="도담식당"

    
    text=f"날짜: {api_response['date']}\n식당: {api_response['restaurant_type']}\n메뉴: {api_response['menu']}"
    body={"channel": "#api-notification","username": "학식봇","text": text,"icon_emoji": ":ghost:"}
    response = requests.post(slack_webhook_url, data=json.dumps(body))
    if response.status_code != 200:
        raise ValueError('Slack message sending failed')
    return True


@monitor(monitor_slug='qq')
def testing_Dodam():
    try:
        api_response = Dodam(date=today).get_menu()
        send_slack_message(api_response)
    except Exception as e:
        sentry_sdk.capture_exception(e)

@monitor(monitor_slug='qq')
def testing_School_Cafeteria():
    try:
        api_response = School_Cafeteria(date=today)
        send_slack_message(api_response)
    except Exception as e:
        sentry_sdk.capture_exception(e)

# testing_Dodam()
# # testing_School_Cafeteria()








