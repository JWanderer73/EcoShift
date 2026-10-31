# One image for everything: API, dashboard, and the four pipeline jobs.
# The command is chosen per ECS task (see infra/serving and infra/training).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[dashboard]"
COPY dashboard ./dashboard

EXPOSE 8000 8501
CMD ["uvicorn", "carbon.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
