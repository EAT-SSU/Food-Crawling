import json
import datetime

import requests
from tenacity import retry,stop_after_attempt,wait_fixed

from functions.common.constant import SLACK_WEBHOOK_URL


def lambda_handler(event, context):
    # TODO implement

    if event.get("date") is not None:
        date = event["date"]
    else:
        date = datetime.date.today().strftime("%Y%m%d")

    response = invoke_dormitory_lambda_request(date)
    body = json.dumps(response.json(), ensure_ascii=False).encode("utf-8")

    return {
        'statusCode': 200,
        'body': body
    }
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def invoke_dormitory_lambda_request(date):
    response = requests.get("https://drvrj3q50b.execute-api.ap-northeast-2.amazonaws.com/get_dormitory",
                       params={"date": date})

    return response

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def send_slack_message(date, menu):
    payload = {
        "channel": "#api-notification",
        "username": "학식봇",
        "text": f"기숙사식당({date})의 식단 {menu}",
        "icon_emoji": ":ghost:"
    }
    headers = {'Content-Type': 'application/json'}
    requests.post(SLACK_WEBHOOK_URL, data=json.dumps(payload), headers=headers)

