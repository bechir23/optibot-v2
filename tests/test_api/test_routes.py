import pytest
from fastapi import HTTPException

from app.api import routes


def test_check_auth_fails_closed_when_required_and_missing_key(monkeypatch):
    monkeypatch.setattr(routes.settings, "api_auth_required", True)
    monkeypatch.setattr(routes.settings, "api_key", "")

    with pytest.raises(HTTPException) as exc:
        routes._check_auth(None)

    assert exc.value.status_code == 503


def test_check_auth_accepts_valid_bearer(monkeypatch):
    monkeypatch.setattr(routes.settings, "api_auth_required", True)
    monkeypatch.setattr(routes.settings, "api_key", "secret")

    routes._check_auth("Bearer secret")
