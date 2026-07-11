# AI 智慧產業地圖 — 開發指令
# 執行 `make` 或 `make help` 檢視可用指令。

.DEFAULT_GOAL := help

.PHONY: help seed

help: ## 顯示可用指令清單
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

seed: ## 匯入題材 seeds
	cd backend && uv run python -m cli seed
