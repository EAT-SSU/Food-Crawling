.PHONY: help build deploy clean destroy status logs test env-json

# 설정
STACK_NAME = food-scrapper
REGION = ap-northeast-2
ENV_FILE = .env

# .env에서 파라미터 읽기
-include .env
export

# 환경변수 (배포용)
GPT_API_KEY ?= $(shell grep '^GPT_API_KEY=' .env 2>/dev/null | cut -d '=' -f2-)
SLACK_WEBHOOK_URL ?= $(shell grep '^SLACK_WEBHOOK_URL=' .env 2>/dev/null | cut -d '=' -f2-)
API_BASE_URL ?= $(shell grep '^API_BASE_URL=' .env 2>/dev/null | cut -d '=' -f2-)
DEV_API_BASE_URL ?= $(shell grep '^DEV_API_BASE_URL=' .env 2>/dev/null | cut -d '=' -f2-)

help: ## 도움말 표시
	@printf "\033[0;34mFood Scrapper Makefile\033[0m\n"
	@printf "\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[0;32m%-15s\033[0m %s\n", $$1, $$2}'

env-json: ## .env에서 env.json 생성 (sam local용)
	@printf "\033[0;34m=== env.json 생성 중 ===\033[0m\n"
	@python3 -c '\
import os; \
import json; \
from dotenv import load_dotenv; \
load_dotenv(); \
params = {k: os.getenv(k, "") for k in ["LOG_LEVEL", "AWS_LAMBDA_LOG_LEVEL", "GPT_API_KEY", "SLACK_WEBHOOK_URL", "API_BASE_URL", "DEV_API_BASE_URL", "DODAM_LAMBDA_BASE_URL", "HAKSIK_LAMBDA_BASE_URL", "FACULTY_LAMBDA_BASE_URL", "DORMITORY_LAMBDA_BASE_URL", "SCHEDULING_DODAM_LAMBDA_BASE_URL", "SCHEDULING_HAKSIK_LAMBDA_BASE_URL", "SCHEDULING_FACULTY_LAMBDA_BASE_URL", "SCHEDULING_DORMITORY_LAMBDA_BASE_URL"]}; \
print(json.dumps({"Parameters": params}, indent=2))' > env.json
	@printf "\033[0;32m✓ env.json 생성 완료\033[0m\n"

build: ## SAM 애플리케이션 빌드
	@printf "\033[0;34m=== 빌드 중 ===\033[0m\n"
	sam build --parallel --cached
	@printf "\033[0;32m✓ 빌드 완료\033[0m\n"

deploy: build ## 빌드 후 프로덕션 배포
	@printf "\033[0;34m=== 배포 중 ===\033[0m\n"
	@printf "스택: $(STACK_NAME)\n"
	@printf "API_BASE_URL: $(API_BASE_URL)\n"
	@printf "\n"
	sam deploy \
		--stack-name $(STACK_NAME) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM \
		--no-confirm-changeset \
		--no-fail-on-empty-changeset \
		--resolve-s3 \
		--parameter-overrides \
			GPTApiKey="$(GPT_API_KEY)" \
			SlackWebhookUrl="$(SLACK_WEBHOOK_URL)" \
			ApiBaseUrl="$(API_BASE_URL)" \
			DevApiBaseUrl="$(DEV_API_BASE_URL)"
	@printf "\033[0;32m✓ 배포 완료!\033[0m\n"
	@make status

status: ## 배포 상태 확인
	@printf "\033[0;34m=== 배포 상태 ===\033[0m\n"
	@aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].{Status:StackStatus,Updated:LastUpdatedTime}' \
		--output table 2>/dev/null || printf "\033[0;31m스택이 없습니다\033[0m\n"
	@printf "\n"
	@printf "\033[0;34m=== 엔드포인트 ===\033[0m\n"
	@aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].Outputs' \
		--output table 2>/dev/null || printf "\033[0;31m스택 정보를 가져올 수 없습니다\033[0m\n"

logs: ## Lambda 로그 확인 (FUNCTION=dodam|haksik|faculty|dormitory 필수)
	@if [ -z "$(FUNCTION)" ]; then \
		printf "\033[0;31mError: make logs FUNCTION=dodam\033[0m\n"; \
		exit 1; \
	fi
	@printf "\033[0;34m=== $(FUNCTION) 로그 ===\033[0m\n"
	@FUNCTION_NAME=$$(aws cloudformation describe-stack-resources \
		--stack-name $(STACK_NAME) \
		--query "StackResources[?contains(LogicalResourceId, '$(shell echo $(FUNCTION) | sed 's/\b\(.\)/\u\1/')SchedulingFunction')].PhysicalResourceId" \
		--output text 2>/dev/null); \
	sam logs -n $$FUNCTION_NAME --stack-name $(STACK_NAME) --tail

test: ## 테스트 실행
	@printf "\033[0;34m=== 테스트 실행 ===\033[0m\n"
	pytest tests/ -v

clean: ## 로컬 빌드 파일 정리
	@printf "\033[0;34m=== 정리 중 ===\033[0m\n"
	rm -rf .aws-sam
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@printf "\033[0;32m✓ 정리 완료\033[0m\n"

destroy: ## 스택 삭제
	@printf "\033[0;31m=== 스택 삭제 ===\033[0m\n"
	@read -p "정말로 $(STACK_NAME) 스택을 삭제하시겠습니까? (yes/no): " CONFIRM; \
	if [ "$$CONFIRM" = "yes" ]; then \
		aws cloudformation delete-stack --stack-name $(STACK_NAME); \
		printf "\033[0;33m삭제 대기 중...\033[0m\n"; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_NAME) 2>/dev/null || true; \
		printf "\033[0;32m✓ 삭제 완료\033[0m\n"; \
	else \
		printf "\033[0;31m취소됨\033[0m\n"; \
	fi
