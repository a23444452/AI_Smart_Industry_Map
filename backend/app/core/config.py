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
    # NoDecode: skip pydantic-settings' JSON decoding of the env var so the raw
    # string reaches the validator below (supports comma-separated values).
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        # Accept a comma-separated string (as used in .env.example) in addition
        # to a real list, so AISM_CORS_ORIGINS=http://localhost:5173 works.
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
