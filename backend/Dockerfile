# syntax=docker/dockerfile:1

# Build the locked production environment separately so uv is not shipped at runtime.
FROM python:3.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Keep the runtime image limited to the API, its environment, and Alembic migrations.
FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --from=builder --chown=app:app /app/.venv ./.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app app ./app

USER app

# Railway supplies PORT; the fallback keeps the image convenient to run locally.
CMD ["/bin/sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log"]
