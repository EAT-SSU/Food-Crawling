import asyncio
import json
from logging import getLogger

import aiohttp
from tenacity import retry, stop_after_attempt, wait_fixed

from functions.common.constant import SLACK_WEBHOOK_URL, FACULTY_LAMBDA_BASE_URL
from functions.common.utils import get_next_weekdays, get_current_weekdays


# AWS Lambda에서 실행되는 함수
def lambda_handler(event, context):
    logger = getLogger(context.function_name)

    # 만약 event에 date가 있다면 그 날짜로 실행 없으면 get_next_weekdays로 실행
    if event.get("queryStringParameters") and event.get("queryStringParameters").get("delayed_schedule"):
        weekdays = get_current_weekdays()
    else:
        weekdays = get_next_weekdays()

    body = asyncio.run(main(weekdays))
    body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    return {
        'statusCode': 200,
        'body': body
    }


async def main(weekdays: list):
    results = {}

    async with aiohttp.ClientSession() as session:
        # lambda invoke하는 부분
        tasks = [invoke_faculty_lambda_request(session, date) for date in weekdays]
        responses = await asyncio.gather(*tasks)

        for date, response_data in zip(weekdays, responses):
            results[date] = response_data

        # Slack으로 메뉴 보내는 부분
        tasks = [send_slack_message(session, date, menu) for date, menu in results.items()]
        responses = await asyncio.gather(*tasks)

    return results


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def send_slack_message(session, date, menu):
    payload = {
        "channel": "#api-notification",
        "username": "학식봇",
        "text": f"교직원식당({date})의 식단 {menu}",
        "icon_emoji": ":ghost:"
    }
    headers = {'Content-Type': 'application/json'}
    async with session.post(SLACK_WEBHOOK_URL, data=json.dumps(payload), headers=headers) as response:
        return await response.text()


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def invoke_faculty_lambda_request(session, date):
    async with session.get(url=FACULTY_LAMBDA_BASE_URL, params={"date": date}) as response:
        response_text = await response.text()
        response_data = json.loads(response_text)
        return response_data
