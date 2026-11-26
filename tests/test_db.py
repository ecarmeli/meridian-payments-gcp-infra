"""Unit tests for app/db.py (GCP Cloud SQL Private IP and local TCP modes)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.cloud.sql.connector import IPTypes

import db


def _make_fake_connection(fetchone_result=(1,)) -> tuple[MagicMock, MagicMock]:
    fake_cursor = MagicMock()
    fake_cursor.fetchone.return_value = fetchone_result
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    return fake_conn, fake_cursor


def test_create_cloud_sql_connector_enforces_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector_cls = MagicMock()
    monkeypatch.setattr(db, "Connector", connector_cls)

    db.create_cloud_sql_connector()

    connector_cls.assert_called_once_with(ip_type=IPTypes.PRIVATE)


def test_gcp_mode_connects_with_private_ip_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "false")
    monkeypatch.setenv("CLOUD_SQL_CONNECTION_NAME", "meridian-poc:europe-west1:meridian-pg")
    monkeypatch.setenv("DB_USER", "appuser")
    monkeypatch.setenv("DB_NAME", "appdb")

    fake_conn, fake_cursor = _make_fake_connection((1,))
    fake_connector = MagicMock()
    fake_connector.connect.return_value = fake_conn

    db.check_database_health("fresh-secret-pw", connector=fake_connector)

    fake_connector.connect.assert_called_once_with(
        "meridian-poc:europe-west1:meridian-pg",
        "pg8000",
        user="appuser",
        password="fresh-secret-pw",
        db="appdb",
        ip_type=IPTypes.PRIVATE,
        timeout=5,
    )
    fake_cursor.execute.assert_called_once_with("SELECT 1")
    fake_cursor.close.assert_called_once()
    fake_conn.close.assert_called_once()


def test_gcp_mode_closes_connection_even_when_query_returns_unexpected_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "false")
    monkeypatch.setenv("CLOUD_SQL_CONNECTION_NAME", "meridian-poc:europe-west1:meridian-pg")

    fake_conn, fake_cursor = _make_fake_connection((0,))
    fake_connector = MagicMock()
    fake_connector.connect.return_value = fake_conn

    with pytest.raises(RuntimeError, match="unexpected result"):
        db.check_database_health("fresh-secret-pw", connector=fake_connector)

    fake_cursor.close.assert_called_once()
    fake_conn.close.assert_called_once()


def test_gcp_mode_requires_connection_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "false")
    fake_connector = MagicMock()

    with pytest.raises(RuntimeError, match="CLOUD_SQL_CONNECTION_NAME"):
        db.check_database_health("fresh-secret-pw", connector=fake_connector)


def test_local_mode_connects_directly_over_pg8000_tcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("DB_HOST", "postgres")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "appuser")
    monkeypatch.setenv("DB_NAME", "appdb")

    fake_conn, fake_cursor = _make_fake_connection((1,))
    connect_mock = MagicMock(return_value=fake_conn)
    monkeypatch.setattr(db.pg8000.dbapi, "connect", connect_mock)

    db.check_database_health("local-secret-pw")

    connect_mock.assert_called_once_with(
        host="postgres",
        port=5432,
        user="appuser",
        password="local-secret-pw",
        database="appdb",
        timeout=5,
    )
    fake_cursor.execute.assert_called_once_with("SELECT 1")
    fake_cursor.close.assert_called_once()
    fake_conn.close.assert_called_once()
