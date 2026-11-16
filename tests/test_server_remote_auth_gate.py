"""
Tests verifying that remote access strictly requires authentication
while localhost (127.0.0.1:8501) operates with zero-friction automatic admin access.
"""
import json
import pytest
from unittest.mock import MagicMock
from jarvis.api.server import JarvisRequestHandler
from jarvis.api.remote_auth import RemoteAuthEngine


def make_mock_handler(client_ip="203.0.113.195", headers=None, path="/api/telemetry_state"):
    """Creates a mock JarvisRequestHandler with specified headers and client address."""
    handler = object.__new__(JarvisRequestHandler)
    handler.client_address = (client_ip, 54321)
    handler.headers = headers or {}
    handler.path = path
    handler.responses = []
    
    def _send_json(data, status_code=200, cookies=None):
        handler.responses.append((status_code, data))
    
    handler._send_json = _send_json
    return handler


def test_remote_request_without_token_is_blocked_on_telemetry():
    handler = make_mock_handler(
        client_ip="203.0.113.50",
        headers={"Host": "telemetry.trycloudflare.com", "X-Forwarded-For": "203.0.113.50"},
        path="/api/telemetry_state"
    )
    assert handler._is_local_request() is False
    assert handler._check_auth() is False


def test_localhost_request_has_zero_friction_auth():
    handler = make_mock_handler(
        client_ip="127.0.0.1",
        headers={"Host": "127.0.0.1:8501"},
        path="/api/telemetry_state"
    )
    assert handler._is_local_request() is True
    assert handler._check_auth() is True
    user = handler._get_auth_user()
    assert user is not None
    assert user["username"] == "admin"
    assert user["role"] == "ADMIN"


def test_remote_request_with_valid_token_passes_auth():
    RemoteAuthEngine._init_default_users()
    session = RemoteAuthEngine.create_session_token("admin")
    token = session["token"]

    handler = make_mock_handler(
        client_ip="203.0.113.50",
        headers={
            "Host": "telemetry.trycloudflare.com",
            "X-Forwarded-For": "203.0.113.50",
            "Authorization": f"Bearer {token}"
        },
        path="/api/telemetry_state"
    )
    assert handler._is_local_request() is False
    assert handler._check_auth() is True
    user = handler._get_auth_user()
    assert user is not None
    assert user["username"] == "admin"


def test_remote_request_for_admin_endpoint_requires_admin_role():
    # Non-admin user
    RemoteAuthEngine.register_user("gate_trader", "SafePassword123", "Gate Trader")
    RemoteAuthEngine.approve_user("gate_trader", role="TRADER", approved_by="admin")
    session = RemoteAuthEngine.create_session_token("gate_trader")
    token = session["token"]

    handler = make_mock_handler(
        client_ip="203.0.113.50",
        headers={
            "Host": "telemetry.trycloudflare.com",
            "X-Forwarded-For": "203.0.113.50",
            "Authorization": f"Bearer {token}"
        },
        path="/api/admin/users"
    )
    ok, user = handler._require_role("ADMIN")
    assert ok is False
    assert len(handler.responses) == 1
    status_code, data = handler.responses[0]
    assert status_code == 403
    assert "not permitted" in data.get("error", "").lower()

    # Cleanup
    RemoteAuthEngine.delete_user("gate_trader")


# ── 2026-11-16: data APIs were readable through the public tunnel ────────────

_TUNNEL = {"Host": "x.trycloudflare.com", "X-Forwarded-For": "203.0.113.50"}


@pytest.mark.parametrize("path", ["/api/positions", "/api/history", "/api/radar", "/api/pending_orders", "/api/tunnel_info"])
def test_remote_data_get_without_session_is_401(path):
    handler = make_mock_handler(headers=dict(_TUNNEL), path=path)
    handler.do_GET()
    assert handler.responses and handler.responses[0][0] == 401


def test_auth_probe_stays_public_and_answers_401_not_data():
    handler = make_mock_handler(headers=dict(_TUNNEL), path="/api/auth/verify")
    handler.do_GET()
    assert handler.responses[0][0] == 401
    assert handler.responses[0][1].get("valid") is False


def _post(handler, body=b"{}"):
    import io
    handler.headers = {**handler.headers, "Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.do_POST()
    return handler.responses[-1]


def test_remote_ungated_post_now_requires_session():
    handler = make_mock_handler(headers=dict(_TUNNEL), path="/api/news/refresh")
    assert _post(handler)[0] == 401


def test_trader_cannot_lift_a_risk_halt():
    RemoteAuthEngine.register_user("halt_trader", "SafePassword123", "Halt Trader")
    RemoteAuthEngine.approve_user("halt_trader", role="TRADER", approved_by="admin")
    token = RemoteAuthEngine.create_session_token("halt_trader")["token"]
    for path in ("/api/action/resume_trading", "/api/action/reset_drawdown"):
        handler = make_mock_handler(headers={**_TUNNEL, "Authorization": f"Bearer {token}"}, path=path)
        handler.orchestrator = MagicMock()
        assert _post(handler)[0] == 403
        handler.orchestrator.resume_trading.assert_not_called()
