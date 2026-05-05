FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY dashboard/backend/requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN pip install --no-cache-dir uv

COPY dashboard /app/dashboard

EXPOSE 2148
CMD ["uvicorn", "dashboard.backend.main:app", "--host", "0.0.0.0", "--port", "2148"]
