#!/bin/bash

# Food Scrapper Serverless 배포 스크립트

set -e

# 색상 설정
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Food Scrapper Serverless 배포 시작${NC}"

# 환경 변수 확인
ENVIRONMENT=${1:-dev}
echo -e "${YELLOW}📦 배포 환경: ${ENVIRONMENT}${NC}"

# 필수 파일 존재 확인
if [ ! -f "secrets.yml" ]; then
    echo -e "${RED}❌ secrets.yml 파일이 없습니다. secrets.yml.template을 참고하여 생성해주세요.${NC}"
    exit 1
fi

if [ ! -f "template.yml" ]; then
    echo -e "${RED}❌ template.yml 파일이 없습니다.${NC}"
    exit 1
fi

# Python 의존성 레이어 디렉토리 확인 및 생성
echo -e "${YELLOW}📚 Python 의존성 레이어 준비${NC}"
if [ ! -d "python-requirements-layer" ]; then
    echo "python-requirements-layer 디렉토리 생성..."
    mkdir -p python-requirements-layer/python/lib/python3.9/site-packages
fi

# requirements.txt가 있으면 의존성 설치
if [ -f "requirements.txt" ] && [ ! -z "$(cat requirements.txt)" ]; then
    echo "Python 의존성 설치 중..."
    pip install -r requirements.txt -t python-requirements-layer/python/lib/python3.9/site-packages --upgrade
else
    echo "requirements.txt가 비어있거나 없습니다. 의존성 설치를 건너뜁니다."
    # 빈 레이어 생성 (SAM이 요구함)
    touch python-requirements-layer/python/lib/python3.9/site-packages/.keep
fi

# SAM 빌드
echo -e "${YELLOW}🔨 SAM 빌드 중...${NC}"
sam build --use-container --cached

# SAM 배포
echo -e "${YELLOW}🚀 SAM 배포 중...${NC}"
if [ "$ENVIRONMENT" = "prod" ]; then
    sam deploy --config-env prod --guided
else
    sam deploy --config-env dev
fi

# 배포 완료
echo -e "${GREEN}✅ 배포 완료!${NC}"

# API 엔드포인트 출력
echo -e "${GREEN}📡 API 엔드포인트:${NC}"
sam list endpoints --output table

echo -e "${GREEN}🎉 Food Scrapper Serverless가 성공적으로 배포되었습니다!${NC}"