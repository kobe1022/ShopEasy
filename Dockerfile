# Ein Image fuer alle Services. Welcher Dienst laeuft, bestimmt der Befehl in
# docker-compose.yml (command). Bauen: docker compose build
FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# UV_PYTHON_DOWNLOADS=never: es zaehlt das Python des Images (3.15), nichts nachladen
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Abhaengigkeiten zuerst: diese Schicht wird nur neu gebaut, wenn sich pyproject.toml
# oder uv.lock aendern, nicht bei jeder Codeaenderung.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev
