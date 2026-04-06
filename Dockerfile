FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./alembic.ini ./alembic.ini
COPY ./alembic ./alembic
COPY ./app ./app
COPY ./scripts ./scripts
COPY ./data ./data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
