# Factory test station API plus the agent and eval harness.
FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
COPY agent/requirements.txt agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt
COPY backend backend
COPY agent agent
COPY eval eval
COPY pyproject.toml .
EXPOSE 5000
CMD ["python", "-m", "backend.app"]
