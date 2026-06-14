FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TDO_DB_PATH=/app/data/trading_desk_os.db \
    TDO_REPORTS_DIR=/app/reports

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt /app/requirements-api.txt
RUN pip install --no-cache-dir -r /app/requirements-api.txt

COPY . /app
RUN mkdir -p /app/data /app/reports

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
