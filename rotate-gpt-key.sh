#!/bin/bash
# Rotate the OpenAI key of the food-scrapper stack from the macOS keychain.
#
# 1. Store the new key (hidden prompt, never on the command line):
#      security add-generic-password -U -a eatssu -s food-scrapper-gpt-api-key -w
# 2. Preview:  ./rotate-gpt-key.sh            (creates and describes a change set)
# 3. Apply:    ./rotate-gpt-key.sh execute    (executes the previewed change set)
#
# Only the GPTApiKey parameter changes. The deployed template and the other
# parameters are reused as-is, so no code is rebuilt or redeployed.
set -euo pipefail

STACK_NAME="food-scrapper"
CHANGE_SET_NAME="rotate-gpt-api-key"
KEYCHAIN_ACCOUNT="eatssu"
KEYCHAIN_SERVICE="food-scrapper-gpt-api-key"
export AWS_PROFILE="${AWS_PROFILE:-eatssu}"
export AWS_REGION="ap-northeast-2"
export AWS_PAGER=""

if [ "${1:-}" = "execute" ]; then
    aws cloudformation execute-change-set \
        --stack-name "$STACK_NAME" --change-set-name "$CHANGE_SET_NAME"
    aws cloudformation wait stack-update-complete --stack-name "$STACK_NAME"
    aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --query 'Stacks[0].[StackStatus,LastUpdatedTime]' --output text
    exit 0
fi

GPT_API_KEY="$(security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$KEYCHAIN_SERVICE" -w)"
if [ -z "$GPT_API_KEY" ]; then
    echo "keychain item $KEYCHAIN_SERVICE is empty" >&2
    exit 1
fi

# Validate the key without putting it in argv (visible in `ps`).
status="$(curl -s -o /dev/null -w '%{http_code}' https://api.openai.com/v1/models \
    -H @<(printf 'Authorization: Bearer %s\n' "$GPT_API_KEY"))"
if [ "$status" != "200" ]; then
    echo "OpenAI rejected the keychain key (HTTP $status); stack not changed" >&2
    exit 1
fi
echo "OpenAI key check: HTTP 200"

aws cloudformation delete-change-set \
    --stack-name "$STACK_NAME" --change-set-name "$CHANGE_SET_NAME" 2>/dev/null || true
aws cloudformation wait change-set-delete-complete \
    --stack-name "$STACK_NAME" --change-set-name "$CHANGE_SET_NAME" 2>/dev/null || true

umask 077
input_file="$(mktemp)"
trap 'rm -f "$input_file"' EXIT
GPT_API_KEY="$GPT_API_KEY" STACK_NAME="$STACK_NAME" CHANGE_SET_NAME="$CHANGE_SET_NAME" python3 -c '
import json, os
keep = ["SlackWebhookUrl", "ApiBaseUrl", "DevApiBaseUrl"]
print(json.dumps({
    "StackName": os.environ["STACK_NAME"],
    "ChangeSetName": os.environ["CHANGE_SET_NAME"],
    "UsePreviousTemplate": True,
    "Capabilities": ["CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND"],
    "Parameters": [{"ParameterKey": "GPTApiKey", "ParameterValue": os.environ["GPT_API_KEY"]}]
    + [{"ParameterKey": name, "UsePreviousValue": True} for name in keep],
}))
' > "$input_file"
unset GPT_API_KEY
aws cloudformation create-change-set --cli-input-json "file://$input_file" --query Id --output text
rm -f "$input_file"

aws cloudformation wait change-set-create-complete \
    --stack-name "$STACK_NAME" --change-set-name "$CHANGE_SET_NAME"
aws cloudformation describe-change-set \
    --stack-name "$STACK_NAME" --change-set-name "$CHANGE_SET_NAME" \
    --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,join(`,`,Scope)]' \
    --output table
echo "Review the changes above, then run: $0 execute"
