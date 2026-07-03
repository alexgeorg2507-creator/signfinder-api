# signfinder-api

FastAPI REST API поверх [signfinder-core](https://github.com/alexgeorg2507-creator/signfinder-core).

## Быстрый старт (локально без Docker)

```powershell
cd C:\work\signfinder-api

python -m venv venv
.\venv\Scripts\Activate.ps1

# signfinder-core из локального репо
pip install -e ../signfinder-core/[gcs]

# зависимости API
pip install -e ".[dev]"

# env vars
$env:STORAGE_MODE="local"
$env:STORAGE_PATH="C:\work\signfinder_test_data"
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:API_KEY="test_key_123"

uvicorn app.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/docs

## Docker

```powershell
docker build -t signfinder-api:local .

docker run -p 8000:8080 `
  -e STORAGE_MODE=local `
  -e STORAGE_PATH=/app/data `
  -e ANTHROPIC_API_KEY=sk-ant-... `
  -e API_KEY=test_key_123 `
  -v C:\work\signfinder_test_data:/app/data `
  signfinder-api:local
```

## Smoke tests

```bash
curl http://localhost:8000/healthz
curl -H "Authorization: Bearer test_key_123" http://localhost:8000/v1/templates
curl -X POST http://localhost:8000/v1/analyze \
  -H "Authorization: Bearer test_key_123" \
  -F "file=@contract.pdf" -F "language=ru"
```

## Миграции

Схема управляется Alembic (`alembic/versions/`), эквивалент старых `migrations/*.sql`.
`DATABASE_URL` — async DSN, обычно через Cloud SQL Auth Proxy:

```powershell
cloud-sql-proxy --port=5432 <project>:europe-west1:signfinder-db
$env:DATABASE_URL = "postgresql+asyncpg://signfinder:<пароль>@127.0.0.1:5432/signfinder"
```

```powershell
# Применить на новой БД:
alembic upgrade head

# Fake-apply на уже существующей (test/prod уже на актуальной схеме):
alembic stamp head

# Откат на шаг:
alembic downgrade -1
```

## Деплой

Деплой через Google Cloud Build:

```bash
gcloud builds submit --config cloudbuild.yaml
```

## Архитектура

Stateless. PDF передаётся в теле каждого запроса — документы не хранятся на сервере.

| Endpoint | Описание |
|----------|----------|
| `POST /v1/analyze` | Анализ PDF: якоря + матчинг шаблонов |
| `POST /v1/sign` | Наложить подпись → вернуть PDF |
| `POST /v1/anchor/from-click` | Якорь по координатам клика |
| `POST /v1/preview` | Рендер страницы → PNG |
| `GET/PATCH/DELETE /v1/templates/{id}` | CRUD шаблонов |
| `GET/PUT /v1/signers/{id}` | Профили подписантов |
| `GET/POST/PATCH/DELETE /v1/parties` | Стороны договора |
| `GET/PUT /v1/settings/*` | Конфиг светофора, маркеры |
| `GET /v1/audit` | Журнал решений |
| `GET /healthz`, `/readyz`, `/v1/version` | System |
