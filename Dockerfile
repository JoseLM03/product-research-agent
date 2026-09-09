FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY app ./app
COPY components ./components
COPY hooks ./hooks
COPY lib ./lib
COPY public ./public
COPY vite.config.ts next.config.ts tsconfig.json ./
RUN npm run typecheck && npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 STATIC_DIR=/app/dist/client
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 appuser
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini ./
COPY --from=frontend /build/dist/client ./dist/client
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
