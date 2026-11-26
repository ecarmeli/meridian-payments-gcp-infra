"""Live Secret Manager retrieval for Meridian Payments GCP PoC."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import secretmanager


DEFAULT_SECRET_TIMEOUT_SECONDS = 5.0


def is_local_dev() -> bool:
    """Return True when LOCAL_DEV=true is explicitly set for local Docker testing."""
    return os.getenv("LOCAL_DEV", "false").strip().lower() == "true"


def create_secret_manager_client() -> secretmanager.SecretManagerServiceClient:
    """Create a Secret Manager client whose gRPC channel is reused across requests."""
    return secretmanager.SecretManagerServiceClient()


def close_secret_manager_client(client: Any | None) -> None:
    """Close the Secret Manager client transport cleanly on shutdown."""
    if client is None:
        return
    transport = getattr(client, "transport", None)
    if transport is not None and hasattr(transport, "close"):
        transport.close()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


def _access_latest_secret(
    client: Any,
    project_id: str,
    secret_id: str,
    timeout: float,
) -> str:
    resource_name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(
        request={"name": resource_name},
        timeout=timeout,
    )
    payload = response.payload.data.decode("utf-8")
    if not payload or not payload.strip():
        raise RuntimeError(f"Secret '{secret_id}' returned an empty payload")
    return payload


def fetch_runtime_secrets(
    client: Any | None = None,
    *,
    timeout: float = DEFAULT_SECRET_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Fetch (db_password, api_token) live on every call without caching."""
    if is_local_dev():
        db_password = os.getenv("LOCAL_DB_PASSWORD", "")
        api_token = os.getenv("LOCAL_API_TOKEN", "")
        if not db_password or not db_password.strip():
            raise RuntimeError("LOCAL_DB_PASSWORD is missing or empty")
        if not api_token or not api_token.strip():
            raise RuntimeError("LOCAL_API_TOKEN is missing or empty")
        return db_password, api_token

    project_id = _require_env("GCP_PROJECT_ID")
    db_password_secret_id = _require_env("DB_PASSWORD_SECRET_ID")
    api_token_secret_id = _require_env("API_TOKEN_SECRET_ID")

    owns_client = client is None
    active_client = create_secret_manager_client() if owns_client else client
    try:
        db_password = _access_latest_secret(
            active_client,
            project_id,
            db_password_secret_id,
            timeout=timeout,
        )
        api_token = _access_latest_secret(
            active_client,
            project_id,
            api_token_secret_id,
            timeout=timeout,
        )
        return db_password, api_token
    finally:
        if owns_client:
            close_secret_manager_client(active_client)
