from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# repo root：config.py 位於 backend/app/core/，往上三層即專案根目錄。
# 以此推導 seeds 預設路徑，使匯入不受 cwd 影響（不論從 backend/ 或 repo root 執行皆可）。
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AISM_", env_file=".env")

    db_path: str = "./data/aism.db"
    seeds_dir: str = str(_REPO_ROOT / "data" / "seeds")
    # Only the real service process (uvicorn) should schedule background jobs;
    # tests/CI set AISM_SCHEDULER_ENABLED=false so no timers spin up under pytest.
    scheduler_enabled: bool = True
    # NoDecode: skip pydantic-settings' JSON decoding of the env var so the raw
    # string reaches the validator below (supports comma-separated values).
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # LLM 設定：mock 為零設定預設（無需任何金鑰即可跑）。切換 provider 見 .env.example。
    #   anthropic     需 AISM_LLM_API_KEY
    #   openai_compat 需 AISM_LLM_BASE_URL + AISM_LLM_API_KEY + AISM_LLM_MODEL
    llm_provider: str = "mock"
    llm_model: str = "claude-sonnet-5"
    llm_api_key: str = ""
    llm_base_url: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        # Accept a comma-separated string (as used in .env.example) in addition
        # to a real list, so AISM_CORS_ORIGINS=http://localhost:5173 works.
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
