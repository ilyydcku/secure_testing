# Secure Testing

Веб-приложение для онлайн-тестирования в рамках ВКР
«Разработка и исследование защищенного веб-приложения для онлайн-тестирования».

## Стек

- Python 3.13
- Django 5.2 LTS
- Django REST Framework
- PostgreSQL 18
- psycopg 3
- django-axes
- pytest
- pytest-django
- Playwright for Python

## Локальная подготовка

Создать виртуальное окружение:

```powershell
py -3.13 -m venv .venv
```

Установить зависимости без активации PowerShell-скрипта виртуального окружения:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

### PostgreSQL

Для первой локальной настройки подключиться к PostgreSQL 18:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h 127.0.0.1 -p 5432 -d postgres
```

Создать отдельную роль и базу приложения:

```sql
CREATE ROLE secure_testing WITH LOGIN;
\password secure_testing
CREATE DATABASE secure_testing OWNER secure_testing;
\q
```

Создать локальный `.env` на основе `.env.example`:

```powershell
Copy-Item .env.example .env
notepad .env
```

В `.env` задать реальные локальные значения `DJANGO_SECRET_KEY` и `POSTGRES_PASSWORD`. Остальные PostgreSQL-параметры по умолчанию соответствуют локальной конфигурации проекта.

Перед запуском загрузить переменные окружения из `.env`:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
    }
}
```

Применить миграции:

```powershell
& ".\.venv\Scripts\python.exe" manage.py migrate
```

Проверить Django:

```powershell
& ".\.venv\Scripts\python.exe" manage.py check
```

При необходимости проверить состояние миграций:

```powershell
& ".\.venv\Scripts\python.exe" manage.py showmigrations
```

## Конфигурации

- local development: `DJANGO_DEBUG=True`
- protected: `DJANGO_DEBUG=False`

Через environment variables задаются:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

Локальный `.env` исключен из Git.

## Структура Django apps

- `accounts` - учетные записи пользователей; app label: `accounts`
- `assessments` - тесты, вопросы, попытки, ответы и результаты
- `auditlog` - журналируемые события
- `config` - конфигурация Django-проекта
- `tests` - общая структура автоматизированных тестов

На этапе 11 реализованы custom `User(AbstractUser)`, все 9 согласованных бизнес-моделей, подключение PostgreSQL 18 и первые миграции `0001_initial`.


## Этап 13: проверка session-based аутентификации

Маршруты: `GET /api/auth/csrf/`, `POST /api/auth/login/`,
`GET /api/auth/me/`, `POST /api/auth/logout/`.

Перед входом клиент получает `csrfToken` через `GET /api/auth/csrf/` и
передает его в заголовке `X-CSRFToken` при `POST /api/auth/login/`.
После успешного входа Django ротирует CSRF token. Для последующих
небезопасных запросов следует использовать обновленный CSRF token
(при необходимости повторно вызвать `GET /api/auth/csrf/`).

Только стандартная `SessionAuthentication` используется для защищенных
DRF endpoints. Данные сессии хранятся в PostgreSQL, а клиент получает
HttpOnly session cookie. `SESSION_COOKIE_AGE=1800` (30 минут);
чтение сессии само по себе срок действия не продлевает.

Для локального HTTP использовать `DJANGO_HTTPS=False`. Для реального
защищенного HTTPS-окружения задать `DJANGO_DEBUG=False`, явный
`DJANGO_ALLOWED_HOSTS` и `DJANGO_HTTPS=True` (оба cookie Secure).
Один лишь флаг `DJANGO_HTTPS=True` не настраивает TLS или прокси.

После `git pull` выполнить в настроенном PostgreSQL-окружении:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q
& ".\.venv\Scripts\python.exe" manage.py check
& ".\.venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
```

Отдельно проверить protected-конфигурацию в окружении с соответствующими
значениями `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` и `DJANGO_HTTPS`:

```powershell
& ".\.venv\Scripts\python.exe" manage.py check --deploy
```

`check --deploy` может дополнительно предупреждать о HSTS и HTTPS
redirect, если они еще не настроены для реального HTTPS-стенда.
Не включать перенаправление или HSTS фиктивно на локальном HTTP.
Параметры django-axes и журналирование login/logout остаются задачами
соответственно этапов 21 и 20.
