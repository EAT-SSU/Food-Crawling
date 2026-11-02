#!/bin/bash
# Build without cache and deploy the food-scrapper stack. This stack is prod:
# run it only after the user approves the deployment.
#
# Secrets come only from the macOS keychain (account "eatssu"):
#   food-scrapper-gpt-api-key, food-scrapper-slack-webhook, food-scrapper-dorm-relay-token
# Plain values come from the environment: API_BASE_URL, DEV_API_BASE_URL, DORMITORY_RELAY_URL.
# A value that is not available is left out of --parameter-overrides, so
# CloudFormation keeps the previous stack value. Extra arguments go to sam deploy.
set -euo pipefail
cd "$(dirname "$0")"

STACK_NAME="food-scrapper"
KEYCHAIN_ACCOUNT="eatssu"
export AWS_PROFILE="${AWS_PROFILE:-eatssu}"
export AWS_REGION="ap-northeast-2"
export AWS_PAGER=""

keychain_value() {
    security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$1" -w 2>/dev/null || true
}

overrides=()
add_override() {
    if [ -n "$2" ]; then
        overrides+=("$1=$2")
        echo "parameter $1: new value"
    else
        echo "parameter $1: keep previous value"
    fi
}

add_override GPTApiKey "$(keychain_value food-scrapper-gpt-api-key)"
add_override SlackWebhookUrl "$(keychain_value food-scrapper-slack-webhook)"
add_override DormitoryRelayToken "$(keychain_value food-scrapper-dorm-relay-token)"
add_override ApiBaseUrl "${API_BASE_URL:-}"
add_override DevApiBaseUrl "${DEV_API_BASE_URL:-}"
add_override DormitoryRelayUrl "${DORMITORY_RELAY_URL:-}"

rm -rf .aws-sam
sam build --no-cached

if [ "${#overrides[@]}" -gt 0 ]; then
    sam deploy --stack-name "$STACK_NAME" --region "$AWS_REGION" \
        --no-fail-on-empty-changeset --parameter-overrides "${overrides[@]}" "$@"
else
    sam deploy --stack-name "$STACK_NAME" --region "$AWS_REGION" \
        --no-fail-on-empty-changeset "$@"
fi
