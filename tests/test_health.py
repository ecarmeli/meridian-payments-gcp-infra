"""End-to-end FastAPI unit tests for /health, lifespan, and secret redaction."""

from __future__ import annotations

import io
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from google.cloud.sql.connector import IPTypes

import db
import main
import secret_manager


def _secret_response(value: str) -> SimpleNamespace:
    return SimpleNamespace(payload=SimpleNamespace(data=value.encode("utf-8")))


def _make_gcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DEV", "false")
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    monkeypatch.setenv("GCP_REGION", "europe-west1")
    monkeypatch.setenv("GCP_PROJECT_ID", "meridian-poc-prod")
    monkeypatch.setenv("DB_PASSWORD_SECRET_ID", "db-password")
    monkeypatch.setenv("API_TOKEN_SECRET_ID", "third-party-api-token")
    monkeypatch.setenv("CLOUD_SQL_CONNECTION_NAME", "meridian-poc-prod:europe-west1:pg-main")


def _capture_meridian_logs() -> tuple[io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(main.JsonLogFormatter())
    main.logger.addHandler(handler)
    return stream, handler


def test_gcp_mode_health_happy_path_reuses_clients_but_never_caches_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_gcp_env(monkeypatch)

    fake_secret_client = MagicMock()
    fake_secret_client.access_secret_version.side_effect = [
        _secret_response("super-secret-pw-1"),
        _secret_response("super-secret-tok-1"),
        _secret_response("super-secret-pw-2"),
        _secret_response("super-secret-tok-2"),
    ]
    create_secret_client_mock = MagicMock(return_value=fake_secret_client)
    monkeypatch.setattr(secret_manager, "create_secret_manager_client", create_secret_client_mock)

    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = (1,)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor

    fake_connector = MagicMock()
    fake_connector.connect.return_value = fake_conn
    create_connector_mock = MagicMock(return_value=fake_connector)
    monkeypatch.setattr(db, "create_cloud_sql_connector", create_connector_mock)

    with TestClient(main.app) as client:
        resp1 = client.get("/health")
        resp2 = client.get("/health")

    assert resp1.status_code == 200
    assert resp1.json() == {
        "candidate": "Erez Carmeli",
        "commit": "abc1234",
        "region": "europe-west1",
        "db": "ok",
        "secret": "ok",
    }
    assert resp2.status_code == 200

    # Clients initialized once in lifespan and closed cleanly on shutdown
    create_secret_client_mock.assert_called_once()
    create_connector_mock.assert_called_once()
    fake_connector.close.assert_called_once()
    fake_secret_client.transport.close.assert_called_once()

    # Secrets fetched live on every request (2 secrets x 2 requests = 4 calls)
    assert fake_secret_client.access_secret_version.call_count == 4

    # Second DB check used the freshly rotated password and IPTypes.PRIVATE
    assert fake_connector.connect.call_count == 2
    first_db_kwargs = fake_connector.connect.call_args_list[0].kwargs
    second_db_kwargs = fake_connector.connect.call_args_list[1].kwargs
    assert first_db_kwargs["password"] == "super-secret-pw-1"
    assert second_db_kwargs["password"] == "super-secret-pw-2"
    assert first_db_kwargs["ip_type"] == IPTypes.PRIVATE
    assert second_db_kwargs["ip_type"] == IPTypes.PRIVATE


def test_gcp_mode_secret_failure_returns_503_and_redacts_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_gcp_env(monkeypatch)
    sentinel_secret = "TOP_SECRET_API_TOKEN_987654"

    fake_secret_client = MagicMock()
    fake_secret_client.access_secret_version.side_effect = RuntimeError(
        f"upstream error containing {sentinel_secret}"
    )
    monkeypatch.setattr(
        secret_manager,
        "create_secret_manager_client",
        MagicMock(return_value=fake_secret_client),
    )

    fake_connector = MagicMock()
    monkeypatch.setattr(
        db,
        "create_cloud_sql_connector",
        MagicMock(return_value=fake_connector),
    )

    log_stream, handler = _capture_meridian_logs()
    try:
        with TestClient(main.app) as client:
            resp = client.get("/health")
    finally:
        main.logger.removeHandler(handler)

    assert resp.status_code == 503
    assert resp.json() == {
        "candidate": "Erez Carmeli",
        "commit": "abc1234",
        "region": "europe-west1",
        "db": "error",
        "secret": "error",
    }
    # DB check must not run when secret retrieval fails
    fake_connector.connect.assert_not_called()

    # Neither response body nor logs may leak the secret or raw exception text
    assert sentinel_secret not in resp.text
    assert sentinel_secret not in log_stream.getvalue()
    assert "upstream error" not in resp.text
    assert "upstream error" not in log_stream.getvalue()


def test_gcp_mode_db_failure_returns_503_and_redacts_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_gcp_env(monkeypatch)
    sentinel_password = "ULTRA_SECRET_DB_PASSWORD_12345"
    sentinel_token = "ULTRA_SECRET_API_TOKEN_67890"

    fake_secret_client = MagicMock()
    fake_secret_client.access_secret_version.side_effect = [
        _secret_response(sentinel_password),
        _secret_response(sentinel_token),
    ]
    monkeypatch.setattr(
        secret_manager,
        "create_secret_manager_client",
        MagicMock(return_value=fake_secret_client),
    )

    fake_connector = MagicMock()
    fake_connector.connect.side_effect = ConnectionError(
        f"postgres://appuser:{sentinel_password}@10.10.0.5:5432/appdb failed"
    )
    monkeypatch.setattr(
        db,
        "create_cloud_sql_connector",
        MagicMock(return_value=fake_connector),
    )

    log_stream, handler = _capture_meridian_logs()
    try:
        with TestClient(main.app) as client:
            resp = client.get("/health")
    finally:
        main.logger.removeHandler(handler)

    assert resp.status_code == 503
    assert resp.json() == {
        "candidate": "Erez Carmeli",
        "commit": "abc1234",
        "region": "europe-west1",
        "db": "error",
        "secret": "ok",
    }

    logs = log_stream.getvalue()
    for sensitive in (sentinel_password, sentinel_token, "10.10.0.5", "postgres://"):
        assert sensitive not in resp.text
        assert sensitive not in logs


def test_local_mode_skips_gcp_client_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("LOCAL_DB_PASSWORD", "local-pass")
    monkeypatch.setenv("LOCAL_API_TOKEN", "local-tok")

    create_secret_client_mock = MagicMock()
    create_connector_mock = MagicMock()
    monkeypatch.setattr(secret_manager, "create_secret_manager_client", create_secret_client_mock)
    monkeypatch.setattr(db, "create_cloud_sql_connector", create_connector_mock)

    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = (1,)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    monkeypatch.setattr(db.pg8000.dbapi, "connect", MagicMock(return_value=fake_conn))

    with TestClient(main.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"
    assert resp.json()["secret"] == "ok"
    create_secret_client_mock.assert_not_called()
    create_connector_mock.assert_not_called()
