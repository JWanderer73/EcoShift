# One image for everything: the API and the pipeline jobs (the dashboard has its own image, see frontend/).
# The command is chosen per ECS task (see infra/serving and infra/training).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PRICE_MODEL_DIR=/app
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[price]"
# The price model code (unchanged); the trained model file lives in S3, not here.
COPY price_windows ./price_windows

EXPOSE 8000
CMD ["uvicorn", "carbon.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
