from app.core.config import Settings


def test_defaults():
    s = Settings()
    assert s.db_path == "./data/aism.db"
    assert s.cors_origins == ["http://localhost:5173"]


def test_cors_origins_from_comma_string(monkeypatch):
    # Mirrors the .env.example format: AISM_CORS_ORIGINS=http://localhost:5173
    monkeypatch.setenv("AISM_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    s = Settings()
    assert s.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
