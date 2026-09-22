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
