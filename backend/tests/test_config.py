import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    # Keep tests independent of locally exported AISM_* vars; _env_file=None
    # in each test additionally ignores any local .env file.
    monkeypatch.delenv("AISM_DB_PATH", raising=False)
    monkeypatch.delenv("AISM_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("AISM_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AISM_LLM_MODEL", raising=False)
    monkeypatch.delenv("AISM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AISM_LLM_BASE_URL", raising=False)


def test_defaults():
    s = Settings(_env_file=None)
    assert s.db_path == "./data/aism.db"
    assert s.cors_origins == ["http://localhost:5173"]


def test_llm_defaults():
    # mock provider is the zero-config default so the app runs with no secrets.
    s = Settings(_env_file=None)
    assert s.llm_provider == "mock"
    assert s.llm_model == "claude-sonnet-5"
    assert s.llm_api_key == ""
    assert s.llm_base_url == ""


def test_llm_env_overrides(monkeypatch):
    monkeypatch.setenv("AISM_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AISM_LLM_MODEL", "claude-opus-5")
    monkeypatch.setenv("AISM_LLM_API_KEY", "sk-test-123")
    monkeypatch.setenv("AISM_LLM_BASE_URL", "https://example.test/v1")
    s = Settings(_env_file=None)
    assert s.llm_provider == "anthropic"
    assert s.llm_model == "claude-opus-5"
    assert s.llm_api_key == "sk-test-123"
    assert s.llm_base_url == "https://example.test/v1"


def test_cors_origins_from_comma_string(monkeypatch):
    # Mirrors the .env.example format: AISM_CORS_ORIGINS=http://localhost:5173
    monkeypatch.setenv("AISM_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
