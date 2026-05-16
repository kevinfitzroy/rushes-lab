# material-storage-api Dockerfile — Phase B-1
# uv-based build,multi-stage 减体积

# ─── stage 1: build deps ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

# uv 包管理
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./

RUN uv venv /opt/venv \
 && . /opt/venv/bin/activate \
 && uv pip install --no-cache .

# ─── stage 2: runtime ─────────────────────────────────────────────────
FROM python:3.12-slim

# 媒体处理(worker 用)
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY app /app/app
COPY alembic.ini /app/alembic.ini

EXPOSE 8000

# 默认 API server;worker 用 docker-compose override command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
