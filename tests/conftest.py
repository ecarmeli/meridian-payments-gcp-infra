"""Shared pytest configuration and fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests start from a clean, deterministic environment."""
    vars_to_clear = [
        "PORT",
        "CANDIDATE_NAME",
        "GIT_COMMIT",
        "GCP_REGION",
        "LOCAL_DEV",
        "GCP_PROJECT_ID",
        "DB_PASSWORD_SECRET_ID",
        "API_TOKEN_SECRET_ID",
        "CLOUD_SQL_CONNECTION_NAME",
        "DB_NAME",
        "DB_USER",
        "DB_HOST",
        "DB_PORT",
        "LOCAL_DB_PASSWORD",
        "LOCAL_API_TOKEN",
    ]
    for name in vars_to_clear:
        monkeypatch.delenv(name, raising=False)
