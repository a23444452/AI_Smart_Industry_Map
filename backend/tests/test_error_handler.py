"""Tests for the global exception handler in app.main.

A deliberately raising route stands in for any unexpected server-side failure
(e.g. a DB error); the client must receive the fixed opaque payload and never
the exception text. Because the Exception handler is served by Starlette's
ServerErrorMiddleware — OUTSIDE CORSMiddleware — the handler must add CORS
headers itself, or browsers would block the 500 body and the frontend could
never read the friendly error message.
"""

from fastapi.testclient import TestClient

from app.main import create_app

SECRET = "boom-secret-internal-detail"
ALLOWED_ORIGIN = "http://localhost:5173"  # settings.cors_origins default


def _exploding_client() -> TestClient:
    app = create_app()

    @app.get("/api/_test-explode")
    def explode():
        raise RuntimeError(SECRET)

    # raise_server_exceptions=False: let the app's own exception handler render
    # the response instead of the TestClient re-raising into the test.
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_error_returns_opaque_500():
    with _exploding_client() as client:
        r = client.get("/api/_test-explode")

    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "internal", "message": "伺服器發生錯誤"}
    }
    # No leak of the underlying exception text anywhere in the body.
    assert SECRET not in r.text


def test_unhandled_error_includes_cors_headers_for_allowed_origin():
    with _exploding_client() as client:
        r = client.get("/api/_test-explode", headers={"Origin": ALLOWED_ORIGIN})

    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "origin" in r.headers.get("vary", "").lower()
    assert r.json() == {
        "error": {"code": "internal", "message": "伺服器發生錯誤"}
    }


def test_unhandled_error_omits_cors_headers_for_disallowed_origin():
    with _exploding_client() as client:
        r = client.get(
            "/api/_test-explode", headers={"Origin": "https://evil.example"}
        )

    assert r.status_code == 500
    assert "access-control-allow-origin" not in r.headers
