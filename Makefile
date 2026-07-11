# AI 智慧產業地圖 — 開發指令
# 執行 `make` 或 `make help` 檢視可用指令。

.DEFAULT_GOAL := help

.PHONY: help seed fetch backfill dev dev-backend dev-frontend test

help: ## 顯示可用指令清單
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

seed: ## 匯入題材 seeds
	cd backend && uv run python -m cli seed

fetch: ## 抓取台股收盤資料
	cd backend && uv run python -m cli fetch

backfill: ## 回填歷史行情與法人資料
	cd backend && uv run python -m cli backfill

dev: ## 同時啟動後端＋前端開發伺服器
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## 啟動後端（FastAPI，port 8000）
	cd backend && uv run uvicorn --factory app.main:create_app --reload --port 8000

dev-frontend: ## 啟動前端（Vite，port 5173）
	cd frontend && npm run dev

test: ## 執行後端與前端測試
	cd backend && uv run pytest
	cd frontend && npm test
