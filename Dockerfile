FROM python:3.13-slim

# Системные зависимости:
#   PyMuPDF: gcc/g++/git/libffi-dev
#   LibreOffice headless: libreoffice-writer — тот же движок, что использует
#     Word/Google Docs при "Save As PDF". Сохраняет footers, точное позицио-
#     нирование, центровку и шрифты, чего mammoth+weasyprint не умели.
#   Шрифты: fonts-liberation (Times/Arial/Courier substitutes) + carlito
#     (Calibri) + caladea (Cambria) — стандартный MS-compatible набор для
#     LibreOffice server-side конвертации.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    libffi-dev \
    shared-mime-info \
    libreoffice-writer \
    fonts-liberation \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
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
    "pydantic>=2.5" \
    "firebase-admin>=6.5" \
    "asyncpg>=0.29"

# Копируем код
COPY app/ ./app/

ENV PORT=8080

EXPOSE ${PORT}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
