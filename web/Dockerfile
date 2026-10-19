# Built viewer served by the read-only results API. Build context is the repo root.
FROM node:22-slim AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir "flask>=3.0,<4"
COPY backend/__init__.py backend/results_api.py backend/
COPY --from=build /web/dist web/dist
EXPOSE 8080
CMD ["python", "-m", "backend.results_api", "--host", "0.0.0.0", "--port", "8080", "--results", "/results"]
