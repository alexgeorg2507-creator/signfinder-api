FROM python:3.13-slim

# Системные зависимости для PyMuPDF
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# signfinder-core из GitHub (production)
RUN pip install --no-cache-dir \
    "signfinder-core[gcs] @ git+https://github.com/alexgeorg2507-creator/signfinder-core.git@main"

# FastAPI и зависимости
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "python-multipart>=0.0.12" \
    "httpx>=0.27" \
    "pydantic>=2.5"

# Копируем код
COPY app/ ./app/

ENV PORT=8080

EXPOSE ${PORT}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
