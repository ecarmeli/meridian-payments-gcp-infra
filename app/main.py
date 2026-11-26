"""Meridian Payments GCP PoC - Containerized HTTP API Service."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import db
import secret_manager


class JsonLogFormatter(logging.Formatter):
    """Structured JSON formatter compatible with Google Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("meridian_api")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = configure_logging()


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.secret_client = None
    application.state.db_connector = None
    try:
        if secret_manager.is_local_dev():
            logger.info("Starting service in LOCAL_DEV mode")
        else:
            logger.info("Starting service in GCP mode")
            application.state.secret_client = secret_manager.create_secret_manager_client()
            application.state.db_connector = db.create_cloud_sql_connector()
        yield
    finally:
        db.close_cloud_sql_connector(application.state.db_connector)
        secret_manager.close_secret_manager_client(application.state.secret_client)
        application.state.db_connector = None
        application.state.secret_client = None
        logger.info("Service shutdown complete")


app = FastAPI(
    title="Meridian Payments GCP PoC API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health(request: Request) -> JSONResponse:
    candidate = os.getenv("CANDIDATE_NAME", "Erez Carmeli")
    commit = os.getenv("GIT_COMMIT", "unknown")
    region = os.getenv("GCP_REGION", "europe-west1")

    try:
        db_password, _api_token = secret_manager.fetch_runtime_secrets(
            client=getattr(request.app.state, "secret_client", None),
        )
    except Exception as exc:
        logger.error(
            "Health check failed: runtime secret retrieval error (error_type=%s)",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "candidate": candidate,
                "commit": commit,
                "region": region,
                "db": "error",
                "secret": "error",
            },
        )

    try:
        db.check_database_health(
            db_password=db_password,
            connector=getattr(request.app.state, "db_connector", None),
        )
    except Exception as exc:
        logger.error(
            "Health check failed: database connectivity error (error_type=%s)",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "candidate": candidate,
                "commit": commit,
                "region": region,
                "db": "error",
                "secret": "ok",
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "candidate": candidate,
            "commit": commit,
            "region": region,
            "db": "ok",
            "secret": "ok",
        },
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
