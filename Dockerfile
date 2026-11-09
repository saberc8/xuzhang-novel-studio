FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN useradd --uid 10001 --create-home xuzhang && mkdir /app/data && chown xuzhang:xuzhang /app/data
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 NOVEL_DATA_DIR=/app/data
USER xuzhang
EXPOSE 8010
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]
