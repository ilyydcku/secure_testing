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

## Этап 15: объектная авторизация

Добавлены общие серверные функции доступа, без новых рабочих URL:

- `accounts.permissions.check_role`: проверка роли до запроса объектов;
- `accounts/access.py`: ADMIN-доступ к User и отдельный список кандидатов
  STUDENT для TEACHER (только `id`, `username`, активные STUDENT);
- `assessments/access.py`: области Test/Question/AnswerOption/TestAssignment/
  Result для TEACHER и назначенных Test/собственных Attempt/StudentAnswer/Result
  для STUDENT;
- `auditlog/access.py`: область чтения AuditEvent только для ADMIN.

Функции получают актуального `request.user`; технические флаги не дают прав.
Списки фильтруются по владельцу или назначению. Вложенный список сначала
проверяет доступ к родителю: чужой или отсутствующий родитель дает одинаковый
404, а не пустой список. STUDENT не видит DRAFT; Question и StudentAnswer
доступны через собственную незавершенную Attempt, в том числе после закрытия
Test. `student_answer_selection` проверяет принадлежность Question к Test
попытки и AnswerOption к Question, но не сохраняет ответ.

Контракт общего слоя:

- `PermissionDenied`: 403, неподходящая роль/неактивный/анонимный пользователь;
- `Http404("Not found.")`: 404, чужой или отсутствующий объект;
- `ValidationError("Invalid related object.")`: нейтральный 400 для неверных
  связанных ID или недоступного кандидата назначения;
- `LifecycleConflict`: 409 для собственной завершенной Attempt при запросе
  ее содержимого/проверке выбора либо незавершенной Attempt при запросе Result.

В будущих Django/DRF endpoints нужно явно отображать `ValidationError` и
`LifecycleConflict` в согласованные 400/409. 403/404 поддерживаются стандартной
обработкой Django/DRF. Проверочные адаптеры сейчас существуют только в тестах.

QuerySet и модели этого слоя являются внутренними данными, не API-ответами.
Нельзя сериализовать их целиком: whitelist serializers/контексты шаблонов
подключаются на этапах 16-18. В частности, AnswerOption содержит `is_correct`,
а User содержит hash пароля; право получить объект внутри backend не дает
права выдавать все его поля клиенту. Операции записи должны повторно проверить
доступ и lifecycle внутри транзакции после получения требуемых блокировок.
Этап 15 не реализует запись ответов, старт/завершение попыток, назначение тестов,
аннулирование сессий или журналирование и не добавляет новые endpoints.

Добавлены 191 сценарий в `tests/test_object_access_stage15.py`: роли для всех
точек входа, цепочки владельцев, фильтрация списков, подмена ID, нейтральные
ошибки, состояния Attempt, текущие роли и реальные session-запросы Django/DRF.
В окружении ассистента на Python 3.12.14, Django 5.2.17, DRF 3.18.1 с временной
SQLite in-memory: `191 passed in 5.63s`; совместно этапы 13-15:
`254 passed in 23.78s`. Настройки проекта и зависимости не изменены.
Полный прогон всех 286 сценариев на Python 3.13/PostgreSQL 18 пока не выполнен;
этап 15 ожидает этой локальной проверки, включая регресс этапа 12:

```powershell
git pull --ff-only origin master
python -m pytest -v --tb=short
python manage.py check
python manage.py makemigrations --check --dry-run
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

## Этап 14: серверная проверка бизнес-ролей

`accounts/permissions.py` содержит общую проверку `has_role(user, role)`,
DRF permissions `IsStudent`, `IsTeacher`, `IsAdmin` и Django-декоратор
`require_role("STUDENT" | "TEACHER" | "ADMIN")`.
Проверяются аутентификация, `is_active` и текущая `User.role`.
`is_staff` и `is_superuser` не дают дополнительных бизнес-прав;
ADMIN не наследует STUDENT или TEACHER. Отказ возвращает HTTP 403.

DRF permissions используются со стандартной `SessionAuthentication`.
Django-декоратор используется при сохраненном `CsrfViewMiddleware`.
Эти проверки не заменяют CSRF, объектную авторизацию или lifecycle.
Рабочие endpoints следующих этапов еще не добавлены; `/api/auth/me/`
остается доступным любой активной аутентифицированной бизнес-роли.

`tests/test_rbac_stage14.py` содержит 40 сценариев: матрица трех ролей
для Django и DRF, анонимные запросы, технические флаги, смена роли
в существующей сессии, блокировка, CSRF и безопасный отказ при
неизвестной роли. Проверочные маршруты существуют только в тестовом URLconf.

Проверки в окружении разработки ассистента: Python 3.12, Django 5.2.17,
DRF 3.18.1; этапы 13-14 прошли на временной SQLite in-memory базе:
`63 passed in 26.07s`. `manage.py check` без замечаний; проверка
`makemigrations --check --dry-run` с временной SQLite-конфигурацией:
`No changes detected`. Настройки PostgreSQL проекта не изменялись.
Эти результаты не заменяют полный прогон на Python 3.13/PostgreSQL 18,
включая конкурентные тесты этапа 12. До его успешного завершения
этап 14 не объявляется окончательно проверенным.

В локальном окружении с загруженными переменными `.env` выполнить:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -v --tb=short
& ".\.venv\Scripts\python.exe" manage.py check
& ".\.venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
```
