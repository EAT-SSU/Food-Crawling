#!/bin/bash

set -e

# 환경 설정
ENVIRONMENT=${1:-default}
if [ "$ENVIRONMENT" = "default" ]; then
    ENV_FILE="env.json"
else
    ENV_FILE="env-${ENVIRONMENT}.json"
fi

# 색상
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}=== Food Scrapper 배포 ($ENVIRONMENT) ===${NC}"

# 파일 존재 확인
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: $ENV_FILE 파일을 찾을 수 없습니다${NC}"
    exit 1
fi

echo -e "${BLUE}환경 파일: $ENV_FILE${NC}"

# JSON에서 Parameters 객체 내의 값들 추출
echo -e "${BLUE}환경변수 설정 중...${NC}"

# Parameters 객체에서 값 추출 (언더스코어 키명 사용)
GPT_API_KEY=$(python3 -c "import json; print(json.load(open('$ENV_FILE'))['Parameters'].get('GPT_API_KEY', ''))" 2>/dev/null || echo "")
SLACK_WEBHOOK_URL=$(python3 -c "import json; print(json.load(open('$ENV_FILE'))['Parameters'].get('SLACK_WEBHOOK_URL', ''))" 2>/dev/null || echo "")
API_BASE_URL=$(python3 -c "import json; print(json.load(open('$ENV_FILE'))['Parameters'].get('API_BASE_URL', ''))" 2>/dev/null || echo "")
DEV_API_BASE_URL=$(python3 -c "import json; print(json.load(open('$ENV_FILE'))['Parameters'].get('DEV_API_BASE_URL', ''))" 2>/dev/null || echo "")

# 값 확인 (보안상 일부만 표시)
echo -e "${YELLOW}파싱된 값들:${NC}"
echo "GPT_API_KEY: ${GPT_API_KEY:0:10}... (길이: ${#GPT_API_KEY})"
echo "SLACK_WEBHOOK_URL: ${SLACK_WEBHOOK_URL:0:30}... (길이: ${#SLACK_WEBHOOK_URL})"
echo "API_BASE_URL: $API_BASE_URL"
echo "DEV_API_BASE_URL: $DEV_API_BASE_URL"
echo ""

# 중요: 빈 값이어도 배포는 진행 (나중에 수동으로 설정 가능)
if [ -z "$GPT_API_KEY" ]; then
    echo -e "${YELLOW}Warning: GPT_API_KEY가 비어있습니다${NC}"
fi
if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo -e "${YELLOW}Warning: SLACK_WEBHOOK_URL이 비어있습니다${NC}"
fi

# 빌드
echo -e "${BLUE}빌드 중...${NC}"
sam build

# 추가 SAM 옵션들 처리 (첫 번째 인자인 환경명 제외)
shift || true  # 첫 번째 인자(환경) 제거, 실패해도 무시
EXTRA_ARGS="$@"

# 배포 실행 (SAM 템플릿의 파라미터명에 맞춰서 전달)
echo -e "${BLUE}배포 중...${NC}"
if [ -n "$EXTRA_ARGS" ]; then
    echo -e "${YELLOW}추가 옵션: $EXTRA_ARGS${NC}"
fi

sam deploy \
    --config-env "$ENVIRONMENT" \
    --parameter-overrides \
        GPTApiKey="$GPT_API_KEY" \
        SlackWebhookUrl="$SLACK_WEBHOOK_URL" \
        ApiBaseUrl="$API_BASE_URL" \
        DevApiBaseUrl="$DEV_API_BASE_URL" \
    $EXTRA_ARGS

echo -e "${GREEN}배포 완료!${NC}"

# 배포 후 안내
if [ -z "$GPT_API_KEY" ] || [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo ""
    echo -e "${YELLOW}=== 추가 설정 필요 ===${NC}"
    echo "다음 명령어로 누락된 파라미터를 수동으로 설정할 수 있습니다:"
    echo ""
    if [ -z "$GPT_API_KEY" ]; then
        echo "aws ssm put-parameter --name \"/food-scrapper/gpt-api-key\" --value \"sk-your-key\" --type \"SecureString\" --overwrite"
    fi
    if [ -z "$SLACK_WEBHOOK_URL" ]; then
        echo "aws ssm put-parameter --name \"/food-scrapper/slack-webhook\" --value \"https://hooks.slack.com/...\" --type \"SecureString\" --overwrite"
    fi
    echo ""
    echo "또는 env-${ENVIRONMENT}.json 파일에 실제 값을 입력하고 다시 배포하세요."
fi