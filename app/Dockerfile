# Stage 1: Build virtual environment using Debian Trixie's system Python 3.13
# so interpreter path (/usr/bin/python3), stdlib, and C-extension ABI match
# gcr.io/distroless/python3-debian13:nonroot 1:1.
FROM debian:trixie-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 \
        python3-venv && \
    rm -rf /var/lib/apt/lists/* && \
    /usr/bin/python3 -m venv /venv

COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /venv/bin/pip uninstall -y pip

# Stage 2: Google-maintained Distroless runtime (non-root UID 65532, no shell)
FROM gcr.io/distroless/python3-debian13:nonroot

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/venv/bin:${PATH}"

WORKDIR /app

COPY --from=builder /venv /venv
COPY --chown=65532:65532 main.py db.py secret_manager.py /app/

EXPOSE 8080

ENTRYPOINT ["/venv/bin/python", "main.py"]
