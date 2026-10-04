# The demo app (FastAPI + built React frontend). Build context: the repo root.
# On start it applies the database migrations, then serves on port 8000 (behind Caddy).

FROM node:20-bookworm-slim AS frontend
WORKDIR /repo/app/frontend
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKFLOW_DEMO_REPO_ROOT=/repo \
    WORKFLOW_DEMO_CATALOG_DIR=/repo/catalog \
    WORKFLOW_DEMO_FRONTEND_DIST=/repo/app/frontend/dist \
    HOST=0.0.0.0 \
    PORT=8000
WORKDIR /repo/app/backend
COPY app/backend/ ./
RUN pip install --no-cache-dir .
COPY catalog/ /repo/catalog/
COPY --from=frontend /repo/app/frontend/dist /repo/app/frontend/dist
RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec python -m workflow_demo"]
