from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AISM_", env_file=".env")

    db_path: str = "./data/aism.db"
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
