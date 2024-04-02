import os
import base64

import openai

# Secret env
ENCRYPTED = os.environ['GPT_API_KEY']
# DECRYPTED = boto3.client('kms').decrypt(
#             CiphertextBlob=base64.b64decode(ENCRYPTED),
#             EncryptionContext={'LambdaFunctionName': os.environ['AWS_LAMBDA_FUNCTION_NAME']})['Plaintext'].decode('utf-8')
openai.api_key = ENCRYPTED
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
API_BASE_URL = os.getenv("API_BASE_URL")

# AWS lambda base url
DODAM_LAMBDA_BASE_URL = os.getenv("DODAM_LAMBDA_BASE_URL")
HAKSIK_LAMBDA_BASE_URL = os.getenv("HAKSIK_LAMBDA_BASE_URL")
DORMITORY_LAMBDA_BASE_URL = os.getenv("DORMITORY_LAMBDA_BASE_URL")

# 숭실대 생협의 api에서 쓰는 구분자
SOONGGURI_HAKSIK_RCD = 1
SOONGGURI_DODAM_RCD = 2


# 도담식당(점심, 저녁), 학생식당(1000원 조식, 점심), 기숙사식당(아침,점심,저녁)
DODAM_LUNCH_PRICE = 6000
DODAM_DINNER_PRICE = 6000

HAKSIK_ONE_DOLLOR_MORNING_PRICE = 1000
HAKSIK_MORNING_PRICE = 1000
HAKSIK_LUNCH_PRICE = 5000
HAKSIK_DINNER_PRICE = 5000

DORMITORY_MORING_PRICE = 5500
DORMITORY_LUNCH_PRICE = 5500
DORMITORY_DINNER_PRICE = 5500







