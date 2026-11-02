.PHONY: help requirements build deploy clean destroy status logs test

STACK_NAME = food-scrapper
REGION = ap-northeast-2

help: ## 도움말 표시
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[0;32m%-15s\033[0m %s\n", $$1, $$2}'

requirements: ## uv.lock에서 레이어용 layer/requirements.txt 생성
	uv export --no-dev --no-hashes --no-emit-project --frozen -o layer/requirements.txt

build: requirements ## 캐시 없이 SAM 빌드
	rm -rf .aws-sam
	sam build --no-cached

deploy: requirements ## 캐시 없이 빌드 후 배포 (prod 반영, 사용자 승인 후에만 실행)
	./deploy.sh

status: ## 배포 상태 확인
	@aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) --region $(REGION) \
		--query 'Stacks[0].{Status:StackStatus,Updated:LastUpdatedTime}' \
		--output table

logs: ## MenuFunction 로그 확인
	sam logs -n MenuFunction --stack-name $(STACK_NAME) --region $(REGION) --tail

test: ## 테스트 실행
	uv run pytest -q

clean: ## 로컬 빌드 파일 정리
	rm -rf .aws-sam
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true

destroy: ## 스택 삭제
	@read -p "정말로 $(STACK_NAME) 스택을 삭제하시겠습니까? (yes/no): " CONFIRM; \
	if [ "$$CONFIRM" = "yes" ]; then \
		aws cloudformation delete-stack --stack-name $(STACK_NAME) --region $(REGION); \
	else \
		echo "취소됨"; \
	fi
