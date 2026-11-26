"""Live PostgreSQL health checks over Cloud SQL Private IP or local TCP."""

from __future__ import annotations

import os
from typing import Any

import pg8000.dbapi
from google.cloud.sql.connector import Connector, IPTypes

from secret_manager import is_local_dev


DEFAULT_DB_TIMEOUT_SECONDS = 5


def create_cloud_sql_connector() -> Connector:
    """Create a single Cloud SQL Connector locked to Private IP for the app lifespan."""
    return Connector(ip_type=IPTypes.PRIVATE)


def close_cloud_sql_connector(connector: Any | None) -> None:
    """Close the Cloud SQL Connector cleanly on shutdown."""
    if connector is not None:
        connector.close()


def _open_connection(
    db_password: str,
    connector: Any | None,
    timeout: int,
) -> Any:
    db_user = os.getenv("DB_USER", "appuser").strip()
    db_name = os.getenv("DB_NAME", "appdb").strip()

    if is_local_dev():
        db_host = os.getenv("DB_HOST", "postgres").strip()
        db_port = int(os.getenv("DB_PORT", "5432").strip())
        return pg8000.dbapi.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name,
            timeout=timeout,
        )

    instance_connection_name = os.getenv("CLOUD_SQL_CONNECTION_NAME", "").strip()
    if not instance_connection_name:
        raise RuntimeError("Required environment variable 'CLOUD_SQL_CONNECTION_NAME' is not set")
    if connector is None:
        raise RuntimeError("Cloud SQL Connector is not initialized")

    return connector.connect(
        instance_connection_name,
        "pg8000",
        user=db_user,
        password=db_password,
        db=db_name,
        ip_type=IPTypes.PRIVATE,
        timeout=timeout,
    )


def check_database_health(
    db_password: str,
    connector: Any | None = None,
    *,
    timeout: int = DEFAULT_DB_TIMEOUT_SECONDS,
) -> None:
    """Open a fresh PostgreSQL connection, run SELECT 1, and close immediately."""
    conn = _open_connection(db_password=db_password, connector=connector, timeout=timeout)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        if row is None or row[0] != 1:
            raise RuntimeError("Database health query returned an unexpected result")
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass
