"""
Генерирует команды `gcloud scheduler jobs update http` для двух задач Deal
Cycle E5 retention/cleanup (DEAL_CYCLE_SPEC.md §8 E5):
  - deals-expire-sweep — каждый час, чистит файлы истёкших сделок
  - deals-purge-old    — раз в сутки (03:00 UTC), удаляет записи старше 30 дней

TASK_e5_scheduler_auth_followup.md: заголовок Authorization не доходит до
эндпоинта — Cloud Scheduler резервирует это имя под собственный
oauth_token/oidc_token oneof в HttpTarget и молча обнуляет значение,
переданное через --headers, если ни один из них не задан (подтверждено
Google Cloud API reference, HttpTarget.headers field description). Решение —
свой заголовок X-Deals-Cron-Key вместо Authorization (тот же секрет
api-key/API_KEY, только другое имя заголовка); эндпоинты теперь проверяют
его через CronKeyDep (app/dependencies.py::verify_cron_key), не ApiKeyDep.

Использует `update http`, не `create http` — задания уже существуют
(созданы раньше с неработавшим Authorization-заголовком), `create` упадёт
с "already exists". Если задания почему-то нет — команда ниже с `create`
вместо `update` (тот же --update-headers меняется на --headers) тоже
приведена.

Этот скрипт НИЧЕГО не выполняет сам — только печатает готовые команды.
Значение API_KEY нигде не появляется здесь буквально: команды используют
`$(gcloud secrets versions access latest --secret=api-key ...)` — подстановка
резолвится в оболочке ВЛАДЕЛЬЦА в момент запуска команды, не в момент печати
этого текста (GIT_WORKFLOW.md §Явные запреты, пункт 4).

Запуск: python3 monitoring/setup_deals_retention_cron.py [test] [prod]
  (без аргументов — печатает команды для обеих сред)

Дальше — владелец копирует напечатанные команды и выполняет их сам из
своей оболочки (PowerShell или bash — `$(...)`-подстановка работает в обеих).
"""
import sys

_ENVIRONMENTS = {
    "test": {
        "project": "signfinder-cab-test",
        "api_url": "https://signfinder-api-svmlmbccma-ew.a.run.app",
    },
    "prod": {
        "project": "signfinder-prod",
        "api_url": "https://signfinder-api-cvuz6bbb7a-ew.a.run.app",
    },
}

_LOCATION = "europe-west1"

_JOBS = [
    {
        "name": "deals-expire-sweep",
        "schedule": "0 * * * *",
        "path": "/internal/deals/expire-sweep",
        "description": "Deal Cycle E5: hourly purge of expired deal files",
    },
    {
        "name": "deals-purge-old",
        "schedule": "0 3 * * *",
        "path": "/internal/deals/purge-old",
        "description": "Deal Cycle E5: daily hard-delete of 30+ day old deal rows",
    },
]


def print_commands(env: str) -> None:
    cfg = _ENVIRONMENTS[env]
    project = cfg["project"]
    api_url = cfg["api_url"]
    api_key_substitution = (
        f"$(gcloud secrets versions access latest --secret=api-key --project={project})"
    )
    header_value = f"X-Deals-Cron-Key={api_key_substitution}"

    print(f"\n# --- {env} ({project}) ---------------------------------------")
    for job in _JOBS:
        print(f"\n# {job['description']}")
        print(
            f"# Job already exists (created earlier with the broken Authorization header) — update it:"
        )
        print(
            f"gcloud scheduler jobs update http {job['name']} "
            f"--project={project} "
            f"--location={_LOCATION} "
            f'--update-headers="{header_value}"'
        )
        print(f"# If the job doesn't exist for some reason, create it instead:")
        print(
            f"gcloud scheduler jobs create http {job['name']} "
            f"--project={project} "
            f"--location={_LOCATION} "
            f'--schedule="{job["schedule"]}" '
            f'--uri="{api_url}{job["path"]}" '
            f"--http-method=POST "
            f'--headers="{header_value}" '
            f'--time-zone="UTC"'
        )


if __name__ == "__main__":
    envs = sys.argv[1:] or ["test", "prod"]
    for env in envs:
        if env not in _ENVIRONMENTS:
            print(f"Unknown environment: {env!r} — use 'test' and/or 'prod'", file=sys.stderr)
            sys.exit(1)
    for env in envs:
        print_commands(env)

    print(
        "\n# Эти команды НЕ были выполнены этим скриптом — скопируй и запусти\n"
        "# сам из своей оболочки. Значение API_KEY нигде не появилось в этом\n"
        "# выводе буквально, только как $(...) подстановка.\n"
        "#\n"
        "# Проверка после создания:\n"
        "#   gcloud scheduler jobs list --project=<project> --location="
        + _LOCATION
        + "\n"
        "#   gcloud scheduler jobs run <name> --project=<project> --location="
        + _LOCATION
        + "  (ручной триггер, не ждать час/сутки)"
    )
