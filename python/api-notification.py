import requests
import json

def send_slack_message(message, slack_webhook_url):
    """
    Slack Incoming Webhooks를 사용하여 메시지를 보내는 함수
    :param message: 보낼 메시지
    :param slack_webhook_url: Slack Incoming Webhooks URL
    :return: 성공 여부
    """
    headers = {'Content-type': 'application/json'}
    api_response = requests.get("http://13.124.144.37/foods/school_cafeteria?date=20230512").text.encode("utf-8")
    data = {'text': api_response.decode('utf-8')}  # bytes 타입을 str 타입으로 변환 후 데이터 추가

    response = requests.post(slack_webhook_url, headers=headers, data=json.dumps(data))
    if response.status_code != 200:
        raise ValueError('Slack message sending failed')
    return True

send_slack_message(message="This is testing", slack_webhook_url="https://hooks.slack.com/services/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")
