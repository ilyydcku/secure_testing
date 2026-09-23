"""Opt-in browser check against live Django, not the standalone prototype.

RUN_BROWSER_TESTS=1 enables it. CHROMIUM_EXECUTABLE optionally selects a local
Chromium binary; otherwise Playwright uses its installed Chromium.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from django.utils import timezone
from django.db import connections

from accounts.models import User
from assessments.models import Attempt, Test as Assessment, TestAssignment as Assignment

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS') != '1', reason='Set RUN_BROWSER_TESTS=1 to run the live Django browser check.')]


def db_call(operation):
    # Playwright's sync facade runs an event loop in the calling thread.
    # Keep synchronous ORM assertions in a separate thread, without disabling
    # Django's async safety protection.
    def run():
        try:
            return operation()
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(run).result(timeout=10)


def test_teacher_browser_flow(live_server):
    from playwright.sync_api import expect, sync_playwright

    User.objects.create_user(username='browser_teacher', password='BrowserTeacher16!', role='TEACHER')
    student = User.objects.create_user(username='browser_student', role='STUDENT')
    output = Path(os.environ.get('BROWSER_QA_OUTPUT', '/tmp/teacher-stage16-browser'))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        options = {'headless': True}
        if os.environ.get('CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(live_server.url + '/login/')
        page.get_by_label('Имя пользователя', exact=True).fill('browser_teacher')
        page.get_by_label('Пароль', exact=True).fill('BrowserTeacher16!')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page.get_by_role('heading', name='Мои тесты', exact=True)).to_be_visible()
        page.get_by_role('link', name='Создать тест', exact=True).click()
        page.get_by_label('Название теста', exact=True).fill('Проверка браузера')
        page.get_by_label('Максимальное число попыток', exact=True).fill('2')
        page.get_by_role('button', name='Создать черновик', exact=True).click()
        expect(page.get_by_role('heading', name='Проверка браузера', exact=True)).to_be_visible()
        test = db_call(lambda: Assessment.objects.get(title='Проверка браузера'))
        detail_url = live_server.url + f'/teacher/tests/{test.pk}/'
        expect(page.get_by_role('button', name='Активировать', exact=True)).to_be_disabled()
        page.get_by_role('link', name='Добавить вопрос', exact=True).click()
        page.get_by_label('Текст вопроса', exact=True).fill('Выберите правильный ответ')
        page.locator('#id_options-0-text').fill('Первый')
        page.locator('#id_options-1-text').fill('Второй')
        page.get_by_role('button', name='Добавить вариант', exact=True).click()
        page.locator('#id_options-2-text').fill('Третий')
        page.get_by_role('radio', name='Вариант 1 правильный', exact=True).check()
        for width in [390, 900, 1440]:
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth') == width
        page.screenshot(path=str(output / 'teacher-question.png'), full_page=True)
        page.get_by_role('button', name='Сохранить вопрос', exact=True).click()
        expect(page.get_by_role('link', name='Активировать', exact=True)).to_be_visible()
        page.get_by_role('link', name='Изменить вопрос 1', exact=True).click()
        page.get_by_role('radio', name='Вариант 2 правильный', exact=True).check()
        page.get_by_role('button', name='Сохранить вопрос', exact=True).click()
        page.wait_for_url(detail_url)
        assert db_call(lambda: test.question_set.get().answeroption_set.get(is_correct=True).text) == 'Второй'
        page.screenshot(path=str(output / 'teacher-draft.png'), full_page=True)
        page.get_by_role('link', name='Назначения', exact=True).click()
        page.get_by_label('Студент', exact=True).select_option(str(student.pk))
        page.get_by_role('button', name='Назначить', exact=True).click()
        expect(page.get_by_text('Тест назначен.', exact=True)).to_be_visible()
        page.get_by_role('button', name='Назначить', exact=True).click()
        expect(page.get_by_text('Назначение уже существует или тест закрыт.', exact=True)).to_be_visible()
        page.goto(detail_url)
        page.get_by_role('link', name='Активировать', exact=True).click()
        page.get_by_role('link', name='Отмена', exact=True).click()
        db_call(test.refresh_from_db)
        assert test.status == 'DRAFT'
        page.get_by_role('link', name='Активировать', exact=True).click()
        page.get_by_role('button', name='Активировать тест', exact=True).click()
        expect(page.get_by_text('Активен', exact=True)).to_be_visible()
        expect(page.get_by_role('link', name='Добавить вопрос', exact=True)).to_have_count(0)
        attempt = db_call(lambda: Attempt.objects.create(assignment=Assignment.objects.get(test=test), started_at=timezone.now()))
        page.get_by_role('link', name='Закрыть тест', exact=True).click()
        page.get_by_role('link', name='Отмена', exact=True).click()
        expect(page.get_by_text('Активен', exact=True)).to_be_visible()
        page.get_by_role('link', name='Закрыть тест', exact=True).click()
        page.get_by_role('button', name='Подтвердить закрытие', exact=True).click()
        expect(page.get_by_text('Закрыт', exact=True)).to_be_visible()
        db_call(attempt.refresh_from_db)
        assert attempt.completed_at is None
        page.get_by_role('link', name='Назначения', exact=True).click()
        expect(page.get_by_role('button', name='Назначить', exact=True)).to_have_count(0)
        page.goto(detail_url+'results/')
        expect(page.get_by_text('Завершенных результатов пока нет', exact=True)).to_be_visible()
        for width in [390, 900, 1440]:
            page.set_viewport_size({'width': width, 'height': 900})
            for suffix in ['', 'assignments/', 'results/']:
                page.goto(detail_url+suffix)
                assert page.evaluate('document.documentElement.scrollWidth') == width
            page.goto(live_server.url+'/teacher/tests/new/')
            assert page.evaluate('document.documentElement.scrollWidth') == width
        page.screenshot(path=str(output / 'teacher-form.png'), full_page=True)
        page.get_by_role('button', name='Выйти', exact=True).click()
        expect(page.get_by_role('heading', name='Вход в систему', exact=True)).to_be_visible()
        assert errors == []
        browser.close()
