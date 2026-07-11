"""Tests for the global exception handler in app.main.

A deliberately raising route stands in for any unexpected server-side failure
(e.g. a DB error); the client must receive the fixed opaque payload and never
the exception text.
"""

from fastapi.testclient import TestClient

from app.main import create_app

SECRET = "boom-secret-internal-detail"


def test_unhandled_error_returns_opaque_500():
    app = create_app()

    @app.get("/api/_test-explode")
    def explode():
        raise RuntimeError(SECRET)

    # raise_server_exceptions=False: let the app's own exception handler render
    # the response instead of the TestClient re-raising into the test.
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/_test-explode")

    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "internal", "message": "伺服器發生錯誤"}
    }
    # No leak of the underlying exception text anywhere in the body.
    assert SECRET not in r.text
