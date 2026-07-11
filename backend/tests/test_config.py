import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    # Keep tests independent of locally exported AISM_* vars; _env_file=None
    # in each test additionally ignores any local .env file.
    monkeypatch.delenv("AISM_DB_PATH", raising=False)
    monkeypatch.delenv("AISM_CORS_ORIGINS", raising=False)


def test_defaults():
    s = Settings(_env_file=None)
    assert s.db_path == "./data/aism.db"
    assert s.cors_origins == ["http://localhost:5173"]


def test_cors_origins_from_comma_string(monkeypatch):
    # Mirrors the .env.example format: AISM_CORS_ORIGINS=http://localhost:5173
    monkeypatch.setenv("AISM_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
