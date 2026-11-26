"""Unit tests for app/secret_manager.py (GCP and local modes)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import secret_manager


def _make_secret_response(value: str) -> SimpleNamespace:
    return SimpleNamespace(payload=SimpleNamespace(data=value.encode("utf-8")))


def test_gcp_mode_fetches_both_secrets_live_with_exact_resource_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "false")
    monkeypatch.setenv("GCP_PROJECT_ID", "meridian-poc-123")
    monkeypatch.setenv("DB_PASSWORD_SECRET_ID", "meridian-db-pass")
    monkeypatch.setenv("API_TOKEN_SECRET_ID", "meridian-api-token")

    fake_client = MagicMock()
    fake_client.access_secret_version.side_effect = [
        _make_secret_response("db-pass-v1"),
        _make_secret_response("api-tok-v1"),
        _make_secret_response("db-pass-v2"),
        _make_secret_response("api-tok-v2"),
    ]

    first = secret_manager.fetch_runtime_secrets(client=fake_client)
    second = secret_manager.fetch_runtime_secrets(client=fake_client)

    assert first == ("db-pass-v1", "api-tok-v1")
    assert second == ("db-pass-v2", "api-tok-v2")
    assert fake_client.access_secret_version.call_count == 4

    expected_calls = [
        {
            "request": {
                "name": "projects/meridian-poc-123/secrets/meridian-db-pass/versions/latest",
            },
            "timeout": 5.0,
        },
        {
            "request": {
                "name": "projects/meridian-poc-123/secrets/meridian-api-token/versions/latest",
            },
            "timeout": 5.0,
        },
    ]
    actual_first_two = [call.kwargs for call in fake_client.access_secret_version.call_args_list[:2]]
    assert actual_first_two == expected_calls


def test_gcp_mode_rejects_empty_secret_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "meridian-poc-123")
    monkeypatch.setenv("DB_PASSWORD_SECRET_ID", "meridian-db-pass")
    monkeypatch.setenv("API_TOKEN_SECRET_ID", "meridian-api-token")

    fake_client = MagicMock()
    fake_client.access_secret_version.side_effect = [
        _make_secret_response("valid-password"),
        _make_secret_response("   "),
    ]

    with pytest.raises(RuntimeError, match="empty payload"):
        secret_manager.fetch_runtime_secrets(client=fake_client)


def test_gcp_mode_requires_project_and_secret_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "false")
    fake_client = MagicMock()

    with pytest.raises(RuntimeError, match="GCP_PROJECT_ID"):
        secret_manager.fetch_runtime_secrets(client=fake_client)


def test_local_mode_reads_env_and_rejects_blank_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("LOCAL_DB_PASSWORD", "local-pass")
    monkeypatch.setenv("LOCAL_API_TOKEN", "local-tok")

    assert secret_manager.fetch_runtime_secrets() == ("local-pass", "local-tok")

    monkeypatch.setenv("LOCAL_API_TOKEN", "")
    with pytest.raises(RuntimeError, match="LOCAL_API_TOKEN"):
        secret_manager.fetch_runtime_secrets()
