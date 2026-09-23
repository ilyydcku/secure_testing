# Secure Testing

Разработка и исследование защищенного веб-приложения для онлайн-тестирования.

Проект выполняется в рамках ВКР. Цель проекта - разработать веб-приложение для создания, назначения и прохождения тестов с серверным разграничением прав доступа и последующим исследованием механизмов безопасности.

## Текущий статус

На текущий момент завершен этап 16: реализована функциональность преподавателя.

В рабочем Django-приложении доступны:

- вход и выход через Django Sessions;
- создание и редактирование тестов в статусе DRAFT;
- создание и редактирование вопросов и вариантов ответов;
- активация теста;
- назначение теста активным студентам;
- просмотр назначений;
- закрытие теста;
- просмотр итоговых результатов;
- серверные проверки бизнес-роли и доступа к объектам;
- CSRF-защита unsafe-запросов;
- транзакционные проверки при изменении данных.

Интерфейсы STUDENT и ADMIN пока не реализованы в рабочем Django-приложении. Их пользовательские сценарии представлены в отдельном интерактивном прототипе и будут перенесены на следующих этапах.

## Роли

- TEACHER - создание и управление собственными тестами, вопросами, назначениями и просмотр результатов.
- STUDENT - прохождение назначенных тестов и просмотр собственных результатов.
- ADMIN - управление учетными записями, ролями, блокировками и просмотр журнала событий.

Права ролей разделены. ADMIN не получает автоматически права TEACHER или STUDENT.

## Архитектура

Проект представляет собой модульный монолит на Django.

Основные приложения:

- `accounts/` - учетные записи, аутентификация, роли и проверки доступа;
- `assessments/` - тесты, вопросы, варианты ответов, назначения, попытки и результаты;
- `auditlog/` - журналируемые события;
- `config/` - настройки и маршрутизация Django;
- `tests/` - автоматизированные тесты.

В проекте используются Django Templates для серверного веб-интерфейса и Django REST Framework для API. Основная база данных - PostgreSQL.

## Модель данных

В проекте используются девять основных моделей:

- User
- Test
- Question
- AnswerOption
- TestAssignment
- Attempt
- StudentAnswer
- Result
- AuditEvent

Жизненный цикл теста:

`DRAFT -> ACTIVE -> CLOSED`

Жизненный цикл попытки:

`IN_PROGRESS -> COMPLETED`

## Безопасность

На текущем этапе реализованы:

- Django Sessions;
- DRF SessionAuthentication;
- CSRF-защита;
- проверка текущей бизнес-роли;
- объектная авторизация;
- нейтральный ответ 404 для чужих и отсутствующих объектов;
- ограничение выдаваемых клиенту полей;
- серверная проверка состояния объектов;
- atomic-транзакции для критичных операций этапа 16;
- HttpOnly session cookie;
- возможность включения Secure-флагов cookies через `DJANGO_HTTPS=True`.

Дополнительные механизмы защиты и экспериментальная часть ВКР реализуются на последующих этапах.

## Технологии

- Python 3.13
- Django 5.2
- Django REST Framework
- PostgreSQL 18
- psycopg 3
- Django ORM
- Django Templates
- HTML / CSS / JavaScript
- pytest
- pytest-django
- Playwright for Python

Точные версии Python-зависимостей находятся в `requirements.txt`.

## Макет интерфейса

Дизайн интерфейса:

[Figma](https://www.figma.com/design/eNkNmYR14uYHoMhe23Ekw6?node-id=4-3&p=f&t=MINy446nWQ9kgu4y-0)

Интерактивный прототип 24 экранов:

[design/ui-prototype](https://github.com/ilyydcku/secure_testing/tree/design/ui-prototype/design-prototype)

Прототип предназначен для демонстрации интерфейсов и пользовательских сценариев. Он использует демонстрационные данные и не заменяет серверную реализацию Django.

## Локальный запуск

Требования:

- Python 3.13
- PostgreSQL 18

Создать виртуальное окружение:

```powershell
py -3.13 -m venv .venv
```

Установить зависимости:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

Создать локальный `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

В `.env` необходимо задать собственные значения `DJANGO_SECRET_KEY` и `POSTGRES_PASSWORD`.

Загрузить переменные окружения:

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

Проверить конфигурацию:

```powershell
& ".\.venv\Scripts\python.exe" manage.py check
```

Запустить сервер:

```powershell
& ".\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
```

После запуска открыть:

`http://127.0.0.1:8000/login/`

Для доступа к реализованному кабинету преподавателя требуется активная учетная запись с ролью TEACHER.

## Тестирование

Полный набор тестов запускается командой:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -v --tb=short
```

Дополнительные проверки:

```powershell
& ".\.venv\Scripts\python.exe" manage.py check
& ".\.venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
```

На проверенной реализации этапа 16 локальный прогон с PostgreSQL завершился результатом:

`420 passed, 1 skipped`

Один отдельно включаемый браузерный тест в этом локальном прогоне не запускался.

## Структура репозитория

```text
secure_testing/
├── accounts/
├── assessments/
├── auditlog/
├── config/
├── docs/
├── tests/
├── .env.example
├── .gitignore
├── manage.py
├── pytest.ini
├── requirements.txt
└── README.md
```
