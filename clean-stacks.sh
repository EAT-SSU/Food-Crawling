#!/bin/bash

set -e

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== AWS CloudFormation 스택 정리 ===${NC}"
echo ""

# 현재 스택 확인
echo -e "${YELLOW}현재 배포된 스택 확인 중...${NC}"
STACKS=$(aws cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE UPDATE_ROLLBACK_COMPLETE \
    --query 'StackSummaries[].StackName' \
    --output text)

if [ -z "$STACKS" ]; then
    echo -e "${GREEN}삭제할 스택이 없습니다.${NC}"
    exit 0
fi

echo -e "${YELLOW}발견된 스택들:${NC}"
echo "$STACKS" | tr '\t' '\n'
echo ""

# 삭제 확인
read -p "위 스택들을 모두 삭제하시겠습니까? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${RED}취소되었습니다.${NC}"
    exit 1
fi

# 스택 삭제
echo ""
echo -e "${YELLOW}스택 삭제 시작...${NC}"

for STACK in $STACKS; do
    echo -e "${YELLOW}삭제 중: $STACK${NC}"
    aws cloudformation delete-stack --stack-name "$STACK"
done

# 삭제 대기
echo ""
echo -e "${YELLOW}스택 삭제 완료 대기 중... (몇 분 소요될 수 있습니다)${NC}"

for STACK in $STACKS; do
    echo -e "${YELLOW}대기 중: $STACK${NC}"
    aws cloudformation wait stack-delete-complete --stack-name "$STACK" 2>/dev/null || true
    echo -e "${GREEN}✓ $STACK 삭제 완료${NC}"
done

echo ""
echo -e "${GREEN}=== 모든 스택이 삭제되었습니다! ===${NC}"
