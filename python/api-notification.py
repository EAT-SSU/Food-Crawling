import requests
import json
from Object import Dodam,School_Cafeteria
import sentry_sdk
from sentry_sdk.crons import monitor
from fastapi.encoders import jsonable_encoder


from datetime import datetime
import pytz

seoul_timezone = pytz.timezone('Asia/Seoul')
current_time = datetime.now(seoul_timezone)
today = current_time.date().strftime("%Y%m%d")

print(today)



sentry_sdk.init(
    dsn="https://94230547ab4e4ce483f714b4077f4572@o4505178008190976.ingest.sentry.io/4505178011009024",

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
    slack_webhook_url="https://hooks.slack.com/services/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"

    text=f"날짜: {api_response['date']}\n식당: {api_response['restaurant_type']}\n메뉴: {api_response['menu']}"
    data={"channel": "#api-notification","username": "webhookbot","text": text,"icon_emoji": ":ghost:"}
    response = requests.post(slack_webhook_url, data=json.dumps(data))
    if response.status_code != 200:
        raise ValueError('Slack message sending failed')
    return True


@monitor(monitor_slug='qq')
def testing_Dodam():
    try:
        api_response = Dodam(date=today).get_menu()
        print(api_response)
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
# testing_School_Cafeteria()






