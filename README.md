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

Активировать:

```powershell
.\.venv\Scripts\Activate.ps1
```

Установить зависимости:

```powershell
python -m pip install -r requirements.txt
```

Создать локальный `.env` на основе `.env.example` и задать собственный `DJANGO_SECRET_KEY`.

Перед запуском загрузить переменные окружения из `.env`:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
    }
}
```

## Конфигурации

- local development: `DJANGO_DEBUG=True`
- protected: `DJANGO_DEBUG=False`

В обеих конфигурациях `DJANGO_SECRET_KEY` и `DJANGO_ALLOWED_HOSTS` задаются через environment variables.

Проверка Django:

```powershell
python manage.py check
```

## Структура Django apps

- `accounts` - учетные записи пользователей; app label: `accounts`
- `assessments` - тесты, вопросы, попытки, ответы и результаты
- `auditlog` - журналируемые события
- `config` - конфигурация Django-проекта

Модели и миграции создаются начиная с этапа 11.

