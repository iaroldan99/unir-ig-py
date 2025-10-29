# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
  && rm -rf /var/lib/apt/lists/*

# 1) Instalar deps primero para cachear
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Copiar TODO el repo (no solo app/)
COPY . .

EXPOSE 8080

# 3) Start command: usar sh -c para expandir ${PORT}
#    exec para que señales lleguen al proceso uvicorn
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --log-level debug"]
